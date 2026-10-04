"""The load job, and the answers calendar-svc gives (business days, closes).

The load job: golden calendars rebuilt from mkt-data's near-raw rows.

Run by Airflow (POST /jobs/load) whenever mkt-data's calendar DAGs mark the
Asset `mkt_data_calendar_sources`, and nightly. It reads every source the
calendars name from mkt-data, then applies each calendar's sources in
precedence order (golden.build). Idempotent: the same near-raw rows change
nothing. Every run is a `load_run` row, which the metrics read.
"""

import json
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendars import golden
from app.calendars.definitions import CALENDARS
from app.models import Calendar, CalendarDay, CalendarYear, LoadRun


class LoadError(RuntimeError):
    pass


def all_source_names() -> list[str]:
    return [name for cal in CALENDARS.values() for name in cal.source_names]


def run_load(s: Session, fetch) -> dict:
    """fetch(names) -> (states by source name, per-source info). Commits; raises LoadError on failure."""
    started = datetime.now(UTC)
    try:
        states, info = fetch(all_source_names())
        out = {"calendars": [golden.build(s, cal, states, now=started) for cal in CALENDARS.values()], "mkt_data": info}
    except Exception as e:  # recorded, then reported to Airflow as a failure
        s.rollback()
        detail = f"{type(e).__name__}: {e}"[:2000]
        s.add(LoadRun(started_at=started, finished_at=datetime.now(UTC), outcome="error", detail=detail))
        s.commit()
        raise LoadError(detail) from e
    summary = {c["calendar"]: sum(x.get("added", 0) + len(x.get("changed", [])) for x in c["sources"]) for c in out["calendars"]}
    s.add(LoadRun(started_at=started, finished_at=datetime.now(UTC), outcome="ok", detail=json.dumps({"changes": summary})))
    s.commit()
    return out


class UnknownCalendar(LookupError):
    pass


class NotCovered(LookupError):
    pass


def _kind_of(cal_def) -> dict[str, str]:
    return {src.name: src.kind for src in cal_def.sources}


def business_day(s: Session, name: str, day: date) -> dict:
    """Is `day` a business day for this calendar? The same answer mkt-data gave in phase 1.

    Weekends are closed. A year no source covers raises NotCovered. An answer
    from a projected year (rules run forward, no publisher yet) says
    "projected": true: a best guess, not a published date.
    """
    cal_def = CALENDARS.get(name)
    if cal_def is None:
        raise UnknownCalendar(f"unknown calendar {name!r}; known: {sorted(CALENDARS)}")
    out = {"calendar": name, "date": day.isoformat()}
    if day.weekday() >= 5:
        return out | {"business_day": False, "status": "weekend"}
    cal = s.scalar(select(Calendar).where(Calendar.name == name))
    year = s.get(CalendarYear, (cal.id, day.year)) if cal else None
    if year is None:
        raise NotCovered(f"{name} has no published dates for {day.year}")
    if _kind_of(cal_def).get(year.source) == "projected":
        out["projected"] = True
    row = s.scalar(
        select(CalendarDay).where(CalendarDay.calendar_id == cal.id, CalendarDay.day == day, CalendarDay.valid_to.is_(None))
    )
    if row is None:
        return out | {"business_day": True, "status": "open"}
    out |= {"business_day": row.status != "closed", "status": row.status, "holiday": row.holiday}
    if row.close_time is not None:
        out["close_time"] = row.close_time.isoformat(timespec="minutes")
    return out


def closes(s: Session, name: str, start: date, end: date) -> list[dict]:
    """The calendar's closed and early-close weekdays from start to end (inclusive), by date."""
    cal_def = CALENDARS.get(name)
    if cal_def is None:
        raise UnknownCalendar(f"unknown calendar {name!r}; known: {sorted(CALENDARS)}")
    cal = s.scalar(select(Calendar).where(Calendar.name == name))
    if cal is None:
        return []
    kind = _kind_of(cal_def)
    projected = {y.year for y in s.scalars(select(CalendarYear).where(CalendarYear.calendar_id == cal.id))
                 if kind.get(y.source) == "projected"}
    rows = s.scalars(
        select(CalendarDay).where(
            CalendarDay.calendar_id == cal.id, CalendarDay.valid_to.is_(None), CalendarDay.day >= start, CalendarDay.day <= end
        ).order_by(CalendarDay.day)
    ).all()
    return [
        {
            "date": r.day.isoformat(), "status": r.status, "holiday": r.holiday,
            "close_time": r.close_time.isoformat(timespec="minutes") if r.close_time else "",
            "projected": r.day.year in projected, "source": r.source,
        }
        for r in rows
    ]
