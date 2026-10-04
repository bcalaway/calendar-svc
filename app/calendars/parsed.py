"""A source's calendar as one parse states it, and the history-keeping diff.

Ported from mkt-data (app/calendars/parsed.py), where the parsers live: a
source's near-raw rows arrive here as a ParsedCalendar. Pure Python (no
database), so the rules are unit-tested directly.
"""

from dataclasses import dataclass
from datetime import date, time


@dataclass(frozen=True)
class Day:
    """A weekday the calendar is closed (or closes early)."""

    day: date
    status: str  # "closed" | "early_close"
    holiday: str
    close_time: time | None = None


@dataclass(frozen=True)
class ParsedCalendar:
    years: tuple[int, ...]  # every year the source covers, even if a year has no weekday closures
    days: tuple[Day, ...]


@dataclass(frozen=True)
class Diff:
    added: tuple[Day, ...]
    changed: tuple[Day, ...]  # new versions of days whose status, time or name changed
    removed: tuple[date, ...]  # days no longer listed (within the parsed years only)
    held: tuple[date, ...] = ()  # listed differently here, but a higher-precedence source holds them


def diff(
    current: dict[date, Day],
    parsed: ParsedCalendar,
    own: set[date] | None = None,
    blocked: set[date] | frozenset[date] = frozenset(),
) -> Diff:
    """Compare the current rows with a fresh parse, within the parsed years only.

    Years the source no longer lists (the Fed's page rolls forward each year)
    are left alone: dropping off the page isn't a change to the calendar.

    For a calendar with several sources: `own` is the current days this
    source wrote (None means all of them), so it only ever closes off its
    own rows; `blocked` is the days a higher-precedence source holds, which
    this source leaves alone (and reports as `held` if it disagrees).
    """
    years = set(parsed.years)
    new: dict[date, Day] = {}
    held = []
    for d in parsed.days:
        if d.day in blocked:
            if current.get(d.day) != d:
                held.append(d.day)
            continue
        new[d.day] = d
    added, changed = [], []
    for day, d in sorted(new.items()):
        old = current.get(day)
        if old is None:
            added.append(d)
        elif old != d:
            changed.append(d)
    removed = sorted(
        day
        for day in current
        if day.year in years and day not in new and day not in blocked and (own is None or day in own)
    )
    return Diff(tuple(added), tuple(changed), tuple(removed), tuple(sorted(held)))
