"""Golden calendars: one calendar per market from its sources' near-raw rows.

Ported from mkt-data's `apply` (app/calendars/service.py, phase 1), which
merged each source into the calendar as it captured it. Here each source's
current near-raw rows (mkt-data's `CalendarSources.GetSource`) arrive as a
SourceState, and `build` applies the calendar's sources in precedence order,
the same order mkt-data's capture job used, so the result is the same
calendar (A4 checks that day for day).

The rules, unchanged from phase 1:

- Within a calendar, a source may write a date unless a higher-precedence
  source's row holds it (then it reports the disagreement as
  `held_by_higher_source`), and closes off only rows it wrote itself.
- A day a source lists exactly as a lower source already holds it becomes
  this source's (`taken_from_lower_source`), so a projection can't retire it
  later (SIFMA-US 2027, mkt-data #30).
- A projected source fills only years no higher source covers, and works by
  whole years: once a higher source covers a year, the projection's rows for
  it are retired (`retired_for_published_years`), not just the dates the
  publisher happens to list.
- Coverage years stay credited to the highest-precedence source covering them.
- History: a changed or dropped date gets `valid_to` and a new row; years a
  source stops listing are left alone.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendars.definitions import CalendarDef
from app.calendars.parsed import Day, ParsedCalendar, diff
from app.models import Calendar, CalendarDay, CalendarYear


@dataclass
class SourceState:
    """One source's current near-raw rows, as mkt-data serves them."""

    name: str
    years: dict[int, int] = field(default_factory=dict)  # year -> mkt-data capture id
    days: dict[date, tuple[Day, int]] = field(default_factory=dict)  # day -> (Day, capture id)

    @property
    def parsed(self) -> ParsedCalendar:
        return ParsedCalendar(tuple(sorted(self.years)), tuple(d for d, _ in sorted(self.days.values(), key=lambda x: x[0].day)))


def calendar_row(s: Session, cal_def: CalendarDef) -> Calendar:
    cal = s.scalar(select(Calendar).where(Calendar.name == cal_def.name))
    if cal is None:
        cal = Calendar(name=cal_def.name, description=cal_def.description, timezone=cal_def.timezone)
        s.add(cal)
        s.flush()
    elif (cal.description, cal.timezone) != (cal_def.description, cal_def.timezone):
        cal.description, cal.timezone = cal_def.description, cal_def.timezone
    return cal


def apply(s: Session, cal_def: CalendarDef, rank: int, state: SourceState, now: datetime) -> dict:
    """Apply one source (at `rank`) to the calendar, with history and precedence. Flushes."""
    cal = calendar_row(s, cal_def)
    rank_of = {name: i for i, name in enumerate(cal_def.source_names)}
    lowest = len(cal_def.sources)  # rows from a source the calendar no longer lists

    def r(source: str) -> int:
        return rank_of.get(source, lowest)

    parsed = state.parsed
    rows = s.scalars(
        select(CalendarDay).where(CalendarDay.calendar_id == cal.id, CalendarDay.valid_to.is_(None))
    ).all()
    by_day = {x.day: x for x in rows}
    current = {x.day: Day(x.day, x.status, x.holiday, x.close_time) for x in rows}
    own = {x.day for x in rows if r(x.source) == rank}
    years = {y.year: y for y in s.scalars(select(CalendarYear).where(CalendarYear.calendar_id == cal.id))}
    retired: list[date] = []
    if cal_def.sources[rank].projected:
        higher = {y for y, row in years.items() if r(row.source) < rank}
        parsed = ParsedCalendar(
            tuple(y for y in parsed.years if y not in higher),
            tuple(x for x in parsed.days if x.day.year not in higher),
        )
        retired = sorted(day for day in own if day.year in higher)
        own -= set(retired)
    blocked = {x.day for x in rows if r(x.source) < rank}
    d = diff(current, parsed, own=own, blocked=blocked)
    lower = {x.day for x in rows if r(x.source) > rank}
    adopted = [x for x in parsed.days if x.day in lower and x.day not in blocked and current.get(x.day) == x]
    for day in [x.day for x in d.changed + tuple(adopted)] + list(d.removed) + retired:
        by_day[day].valid_to = now
    s.flush()  # close old versions before inserting new ones (unique current row)
    for x in d.added + d.changed + tuple(adopted):
        s.add(
            CalendarDay(
                calendar_id=cal.id, day=x.day, status=x.status, close_time=x.close_time, holiday=x.holiday,
                source=state.name, capture_id=state.days[x.day][1], valid_from=now,
            )
        )
    new_years = []
    for y in parsed.years:
        row = years.get(y)
        if row is None:
            s.add(CalendarYear(calendar_id=cal.id, year=y, source=state.name, capture_id=state.years[y], first_seen_at=now))
            new_years.append(y)
        elif r(row.source) >= rank:
            row.source, row.capture_id = state.name, state.years[y]
    s.flush()
    out = {
        "source": state.name,
        "years": len(parsed.years),
        "new_years": len(new_years),
        "days": len(parsed.days),
        "added": len(d.added),
        "changed": [x.day.isoformat() for x in d.changed],
        "removed": [x.isoformat() for x in d.removed],
    }
    if adopted:
        out["taken_from_lower_source"] = len(adopted)
    if d.held:
        out["held_by_higher_source"] = [x.isoformat() for x in d.held]
    if retired:
        out["retired_for_published_years"] = len(retired)
    return out


def build(s: Session, cal_def: CalendarDef, states: dict[str, SourceState], now: datetime | None = None) -> dict:
    """Apply every source of the calendar in precedence order. Commits.

    A source with no near-raw rows yet (never captured, or kept raw with no
    parser) applies nothing, as in phase 1.
    """
    now = now or datetime.now(UTC)
    results = []
    for rank, src in enumerate(cal_def.sources):
        state = states.get(src.name)
        if state is None or (not state.years and not state.days):
            results.append({"source": src.name, "skipped": "no near-raw rows"})
            continue
        results.append(apply(s, cal_def, rank, state, now))
    s.commit()
    return {"calendar": cal_def.name, "sources": results}
