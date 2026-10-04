"""Prometheus metrics (GET /metrics): the load job and the golden calendars.

Text format, computed from the database on each scrape. Prometheus scrapes it
on the home-platform network as calendar-svc:8000; no auth, like the other
scrape targets, and nothing in it is sensitive. Labels use readable names
(calendar="SIFMA-US"). Part 3 of phase 2's step A3 adds coverage by kind,
gaps and the next-year check.
"""

from datetime import UTC, datetime

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


def render(s) -> str:
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
    cals = {c.name: c.id for c in s.scalars(select(Calendar))}
    days, years, first, last = [], [], [], []
    for name in CALENDARS:
        cid = cals.get(name)
        if cid is None:
            continue
        n = s.scalar(select(func.count()).select_from(CalendarDay).where(CalendarDay.calendar_id == cid, CalendarDay.valid_to.is_(None)))
        ys = s.scalars(select(CalendarYear.year).where(CalendarYear.calendar_id == cid)).all()
        days.append(({"calendar": name}, n))
        years.append(({"calendar": name}, len(ys)))
        if ys:
            first.append(({"calendar": name}, min(ys)))
            last.append(({"calendar": name}, max(ys)))
    out.metric("calendar_svc_calendar_days", "gauge", "Current closed and early-close weekdays per calendar.", days)
    out.metric("calendar_svc_calendar_years", "gauge", "Years each calendar covers (any source).", years)
    out.metric("calendar_svc_calendar_first_year", "gauge", "First year each calendar covers.", first)
    out.metric("calendar_svc_calendar_last_year", "gauge", "Last year each calendar covers.", last)
    return out.text()


@router.get("/metrics")
def metrics() -> Response:
    try:
        with db.session() as s:
            body = render(s)
    except (db.DatabaseNotConfigured, SQLAlchemyError):
        body = "# HELP calendar_svc_up 1 when the database answered this scrape.\n# TYPE calendar_svc_up gauge\ncalendar_svc_up 0\n"
    return Response(body, media_type="text/plain; version=0.0.4")
