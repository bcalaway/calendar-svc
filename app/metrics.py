"""Prometheus metrics (GET /metrics): the load job and the golden calendars.

Text format, computed from the database on each scrape. Prometheus scrapes it
on the home-platform network as calendar-svc:8000; no auth, like the other
scrape targets, and nothing in it is sensitive. Labels use readable names
(calendar="SIFMA-US"). The calendar gauges match mkt-data's phase-1
mkt_data_calendar_* ones, so the Grafana panels and the next-year alert can
switch over (phase 2, step A5); the load gauges are calendar-svc's own.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.calendars.definitions import CALENDARS
from app.models import Calendar, CalendarDay, CalendarYear, LoadRun

router = APIRouter()


def _epoch(t: datetime) -> float:
    # Postgres returns aware timestamps; SQLite (tests) returns naive UTC ones.
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).timestamp()


def _escape(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Out:
    def __init__(self):
        self.lines: list[str] = []

    def metric(self, name: str, kind: str, help_: str, samples: list[tuple[dict, float]]) -> None:
        self.lines += [f"# HELP {name} {help_}", f"# TYPE {name} {kind}"]
        for labels, value in samples:
            body = ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items())
            num = int(value) if float(value).is_integer() else value
            self.lines.append(f"{name}{{{body}}} {num}" if body else f"{name} {num}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


UPCOMING_DAYS = 180  # how far ahead calendar_svc_calendar_upcoming_day lists closes


def _today() -> date:
    return datetime.now(UTC).date()  # a few hours' difference from Eastern doesn't matter here


def render(s, today: date | None = None) -> str:
    today = today or _today()
    out = _Out()
    last_ok = s.scalar(select(func.max(LoadRun.finished_at)).where(LoadRun.outcome == "ok"))
    latest = s.scalar(select(LoadRun).order_by(LoadRun.id.desc()).limit(1))
    out.metric("calendar_svc_up", "gauge", "1 when the database answered this scrape.", [({}, 1)])
    out.metric(
        "calendar_svc_load_last_success_timestamp_seconds", "gauge",
        "When the last successful load from mkt-data's near-raw rows finished.",
        [({}, _epoch(last_ok))] if last_ok else [],
    )
    out.metric(
        "calendar_svc_load_ok", "gauge", "1 if the latest load succeeded, 0 if it failed.",
        [({}, 1 if latest.outcome == "ok" else 0)] if latest else [],
    )

    cal_ids = {c.name: c.id for c in s.scalars(select(Calendar))}
    count, first, last, rows, published, overdue = [], [], [], [], [], []
    gap_count, gap_years, upcoming = [], [], []
    for name, cal_def in CALENDARS.items():
        cid = cal_ids.get(name)
        if cid is None:
            continue
        kind_of = {src.name: src.kind for src in cal_def.sources}
        years = defaultdict(list)  # kind -> [years]
        for y in s.scalars(select(CalendarYear).where(CalendarYear.calendar_id == cid)):
            years[kind_of.get(y.source, "published")].append(y.year)
        for kind, ys in sorted(years.items()):
            labels = {"calendar": name, "kind": kind}
            count.append((labels, len(ys)))
            first.append((labels, min(ys)))
            last.append((labels, max(ys)))
        by_status = dict(s.execute(
            select(CalendarDay.status, func.count())
            .where(CalendarDay.calendar_id == cid, CalendarDay.valid_to.is_(None)).group_by(CalendarDay.status)
        ).all())
        for status in ("closed", "early_close"):
            rows.append(({"calendar": name, "status": status}, by_status.get(status, 0)))
        covered = {y for ys in years.values() for y in ys}
        if covered:
            missing = sorted(set(range(min(covered), max(covered) + 1)) - covered)
            gap_count.append(({"calendar": name}, len(missing)))
            gap_years += [({"calendar": name, "year": str(y)}, 1) for y in missing]
        projected_years = set(years["projected"])
        for d in s.scalars(
            select(CalendarDay).where(
                CalendarDay.calendar_id == cid, CalendarDay.valid_to.is_(None),
                CalendarDay.day >= today, CalendarDay.day <= today + timedelta(days=UPCOMING_DAYS),
            ).order_by(CalendarDay.day)
        ):
            upcoming.append(({
                "calendar": name, "date": d.day.isoformat(), "weekday": f"{d.day:%a}", "holiday": d.holiday,
                "status": d.status, "close_time": d.close_time.strftime("%H:%M") if d.close_time else "",
                "projected": "yes" if d.day.year in projected_years else "no",
            }, (d.day - today).days))
        # Next year counts as published only from a publisher (not rules or a
        # projection), so a projection can't hide a missing year.
        nxt = today.year + 1
        is_published = nxt in years["published"]
        due = date(today.year, *cal_def.next_year_due)
        published.append(({"calendar": name, "year": str(nxt)}, int(is_published)))
        overdue.append(({"calendar": name, "year": str(nxt)}, int(not is_published and today >= due)))
    out.metric("calendar_svc_calendar_days", "gauge", "Current closed and early-close weekdays.", rows)
    out.metric("calendar_svc_calendar_years", "gauge", "Years covered, by kind of source (published, rules, projected).", count)
    out.metric("calendar_svc_calendar_first_year", "gauge", "First covered year, by kind of source.", first)
    out.metric("calendar_svc_calendar_last_year", "gauge", "Last covered year, by kind of source.", last)
    out.metric("calendar_svc_calendar_gap_years", "gauge",
               "Years between the first and last covered year that no source covers.", gap_count)
    out.metric("calendar_svc_calendar_gap_year", "gauge", "1 for each uncovered year inside a calendar's range.", gap_years)
    out.metric("calendar_svc_calendar_upcoming_day", "gauge",
               f"Days from today until each close or early close in the next {UPCOMING_DAYS} days.", upcoming)
    out.metric("calendar_svc_calendar_next_year_published", "gauge",
               "1 if next year is covered by a publisher (not rules or a projection).", published)
    out.metric("calendar_svc_calendar_next_year_overdue", "gauge",
               "1 if next year isn't published yet and is past the calendar's usual publish date.", overdue)
    return out.text()


@router.get("/metrics")
def metrics() -> Response:
    try:
        with db.session() as s:
            body = render(s)
    except (db.DatabaseNotConfigured, SQLAlchemyError):
        body = "# HELP calendar_svc_up 1 when the database answered this scrape.\n# TYPE calendar_svc_up gauge\ncalendar_svc_up 0\n"
    return Response(body, media_type="text/plain; version=0.0.4")
