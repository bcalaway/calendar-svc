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


def coverage(s: Session, name: str) -> list[dict]:
    """Every covered year, by year: the source credited for it and that source's kind."""
    cal_def = CALENDARS.get(name)
    if cal_def is None:
        raise UnknownCalendar(f"unknown calendar {name!r}; known: {sorted(CALENDARS)}")
    cal = s.scalar(select(Calendar).where(Calendar.name == name))
    if cal is None:
        return []
    kind = _kind_of(cal_def)
    return [
        {"year": y.year, "source": y.source, "kind": kind.get(y.source, "published")}
        for y in s.scalars(select(CalendarYear).where(CalendarYear.calendar_id == cal.id).order_by(CalendarYear.year))
    ]


# --- For the Calendars screen (mkt-data's docs/phase-3.md, step 8) ---


def _calendar(s: Session, name: str):
    cal_def = CALENDARS.get(name)
    if cal_def is None:
        raise UnknownCalendar(f"unknown calendar {name!r}; known: {sorted(CALENDARS)}")
    return cal_def, s.scalar(select(Calendar).where(Calendar.name == name))


def sources(s: Session, name: str) -> list[dict]:
    """The calendar's sources in precedence order (highest first), each with the years it's credited for."""
    cal_def, cal = _calendar(s, name)
    credited: dict[str, list[int]] = {}
    if cal is not None:
        for y in s.scalars(select(CalendarYear).where(CalendarYear.calendar_id == cal.id)):
            credited.setdefault(y.source, []).append(y.year)
    return [
        {"name": src.name, "kind": src.kind, "rank": i + 1, "years": len(credited.get(src.name, [])),
         "first_year": min(credited.get(src.name, [0])), "last_year": max(credited.get(src.name, [0]))}
        for i, src in enumerate(cal_def.sources)
    ]


def _iso(t) -> str:
    if t is None:
        return ""
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).isoformat()


def day_history(s: Session, name: str, day: date) -> list[dict]:
    """Every version of the calendar's row for a day, oldest first; the current one has no valid_to. Empty: always open."""
    _, cal = _calendar(s, name)
    if cal is None:
        return []
    rows = s.scalars(select(CalendarDay).where(CalendarDay.calendar_id == cal.id, CalendarDay.day == day)
                     .order_by(CalendarDay.valid_from, CalendarDay.id)).all()
    return [{"date": r.day.isoformat(), "status": r.status, "holiday": r.holiday,
             "close_time": r.close_time.isoformat(timespec="minutes") if r.close_time else "", "source": r.source,
             "capture_id": r.capture_id, "valid_from": _iso(r.valid_from), "valid_to": _iso(r.valid_to)} for r in rows]


def _what(status: str, close_time: str) -> str:
    return "open" if not status else f"{status}{f' {close_time}' if close_time else ''}"


def disagreements(s: Session, name: str, fetch) -> list[dict]:
    """Days where a source (not a projection) says something other than the golden calendar.

    fetch(names) -> (states by source name, info), the same call the load makes (mkt-data's current near-raw rows).
    For each source, within the years it covers: a day it lists differently from the golden row, or lists as closed
    where the calendar is open, or leaves open where the calendar closes. Only days the golden calendar took from
    another source are reported (a source always agrees with what it decided). `differs` says how: status (closed,
    early close or open), time (the early close time) or name (the holiday's name only).
    """
    cal_def, cal = _calendar(s, name)
    if cal is None:
        return []
    states, _ = fetch([src.name for src in cal_def.sources if not src.projected])
    golden = {r.day: r for r in s.scalars(select(CalendarDay).where(CalendarDay.calendar_id == cal.id,
                                                                      CalendarDay.valid_to.is_(None)))}
    rank = {src.name: i for i, src in enumerate(cal_def.sources)}
    out = []
    for src in cal_def.sources:
        state = states.get(src.name)
        if state is None or src.projected:
            continue
        years = set(state.years)
        listed = {day: d for day, (d, _) in state.days.items()}
        days = {d for d in listed if d.year in years} | {d for d, r in golden.items() if d.year in years}
        for day in sorted(days):
            if day.weekday() >= 5:
                continue
            g, mine = golden.get(day), listed.get(day)
            if g is not None and g.source == src.name:
                continue
            g_time = g.close_time.isoformat(timespec="minutes") if g and g.close_time else ""
            m_time = mine.close_time.isoformat(timespec="minutes") if mine and mine.close_time else ""
            g_status, m_status = (g.status if g else ""), (mine.status if mine else "")
            if g_status != m_status:
                differs = "status"
            elif g_time != m_time:
                differs = "time"
            elif g is not None and mine is not None and g.holiday != mine.holiday:
                differs = "name"
            else:
                continue
            decided = g.source if g else ""
            out.append({
                "date": day.isoformat(), "source": src.name, "differs": differs,
                "source_says": _what(m_status, m_time), "source_holiday": mine.holiday if mine else "",
                "calendar_says": _what(g_status, g_time), "calendar_holiday": g.holiday if g else "",
                "decided_by": decided,
                # A higher source holds the day: the usual case. Lower: this source outranks the one that decided,
                # which happens when this source started covering the year after (worth a look).
                "decided_by_higher": decided != "" and rank.get(decided, 99) < rank[src.name],
            })
    return sorted(out, key=lambda x: (x["date"], rank[x["source"]]))
