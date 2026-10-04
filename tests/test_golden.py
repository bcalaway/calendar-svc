"""Golden calendars from sources' near-raw rows (app/calendars/golden.py).

The same rules as mkt-data's phase-1 `apply`, checked with small made-up
calendars: precedence, held dates, a source closing only its own rows, the
projection's whole-year handover, and a publisher taking over identical days.
"""

from datetime import date, time

from sqlalchemy import select

from app import db
from app.calendars import golden
from app.calendars.definitions import CalendarDef, SourceDef
from app.calendars.parsed import Day
from app.models import CalendarDay, CalendarYear

X = CalendarDef(
    "X", "test", "America/New_York",
    (SourceDef("X-PAGE"), SourceDef("X-ARCHIVE"), SourceDef("X-PROJ", "projected")),
)


def _state(name, years, days, capture=1):
    out = golden.SourceState(name, years={y: capture for y in years})
    for d in days:
        out.days[d.day] = (d, capture)
    return out


def _closed(y, m, d, name="Holiday"):
    return Day(date(y, m, d), "closed", name)


def _current(s):
    rows = s.scalars(select(CalendarDay).where(CalendarDay.valid_to.is_(None)).order_by(CalendarDay.day)).all()
    return {r.day: (r.status, r.close_time, r.holiday, r.source) for r in rows}


def _years(s):
    return {y.year: y.source for y in s.scalars(select(CalendarYear))}


def test_sources_merge_in_precedence_order(migrated_db):
    page = _state("X-PAGE", [2026], [_closed(2026, 1, 1, "New Year's Day")])
    archive = _state("X-ARCHIVE", [2025, 2026], [_closed(2025, 12, 25, "Christmas"), _closed(2026, 7, 3, "Independence Day (obs)")])
    with db.session() as s:
        out = golden.build(s, X, {"X-PAGE": page, "X-ARCHIVE": archive})
        cur = _current(s)
        years = _years(s)
    assert [x.get("skipped") for x in out["sources"]] == [None, None, "no near-raw rows"]
    assert cur[date(2026, 1, 1)][3] == "X-PAGE" and cur[date(2025, 12, 25)][3] == "X-ARCHIVE"
    # 2026 stays credited to the higher source; the archive's 2026 day still fills in.
    assert years == {2025: "X-ARCHIVE", 2026: "X-PAGE"} and date(2026, 7, 3) in cur


def test_a_higher_source_holds_a_date_and_the_disagreement_is_reported(migrated_db):
    gf = date(2015, 4, 3)
    page = _state("X-PAGE", [2015], [Day(gf, "early_close", "Good Friday", time(12, 0))])
    archive = _state("X-ARCHIVE", [2015], [_closed(2015, 4, 3, "Good Friday")])
    with db.session() as s:
        out = golden.build(s, X, {"X-PAGE": page, "X-ARCHIVE": archive})
        cur = _current(s)
    assert out["sources"][1]["held_by_higher_source"] == ["2015-04-03"]
    assert cur[gf] == ("early_close", time(12, 0), "Good Friday", "X-PAGE")


def test_a_lower_source_closes_only_its_own_rows(migrated_db):
    page = _state("X-PAGE", [2025], [_closed(2025, 11, 27, "Thanksgiving")])
    archive = _state("X-ARCHIVE", [2025], [_closed(2025, 5, 26, "Memorial Day")])
    with db.session() as s:
        golden.build(s, X, {"X-PAGE": page, "X-ARCHIVE": archive})
    archive2 = _state("X-ARCHIVE", [2025], [], capture=2)  # Memorial Day dropped; Thanksgiving isn't its row
    with db.session() as s:
        out = golden.build(s, X, {"X-PAGE": page, "X-ARCHIVE": archive2})
        cur = _current(s)
    assert out["sources"][1]["removed"] == ["2025-05-26"]
    assert date(2025, 11, 27) in cur and date(2025, 5, 26) not in cur
    with db.session() as s:
        gone = s.scalar(select(CalendarDay).where(CalendarDay.day == date(2025, 5, 26)))
        assert gone.valid_to is not None  # kept as history


def test_a_rebuild_with_the_same_rows_changes_nothing(migrated_db):
    states = {"X-PAGE": _state("X-PAGE", [2026], [_closed(2026, 1, 1)])}
    with db.session() as s:
        golden.build(s, X, states)
    with db.session() as s:
        out = golden.build(s, X, states)["sources"][0]
        n = len(s.scalars(select(CalendarDay)).all())
    assert out["added"] == 0 and out["changed"] == [] == out["removed"] and n == 1


def test_a_projection_fills_only_unpublished_years_and_gives_way_by_whole_years(migrated_db):
    proj = _state("X-PROJ", [2026, 2027, 2028], [
        _closed(2026, 1, 1, "New Year's Day"), _closed(2026, 12, 25, "Christmas Day"),
        _closed(2027, 3, 26, "Good Friday"), _closed(2027, 12, 24, "Christmas Day (observed)"),
        _closed(2028, 1, 3, "New Year's Day (observed)"),
    ])
    page = _state("X-PAGE", [2026], [_closed(2026, 1, 1, "New Year's Day")])
    with db.session() as s:
        out = golden.build(s, X, {"X-PAGE": page, "X-PROJ": proj})
        cur = _current(s)
    assert out["sources"][2]["years"] == 2 and out["sources"][2]["added"] == 3  # 2026 is the publisher's
    assert date(2026, 12, 25) not in cur and cur[date(2027, 3, 26)][3] == "X-PROJ"

    # The publisher adds 2027: an early close on Dec 24, and no Good Friday close.
    page2 = _state("X-PAGE", [2026, 2027], [
        _closed(2026, 1, 1, "New Year's Day"), Day(date(2027, 12, 24), "early_close", "Christmas Eve", time(13, 0)),
    ], capture=2)
    with db.session() as s:
        pub, _, proj_out = golden.build(s, X, {"X-PAGE": page2, "X-PROJ": proj})["sources"]
        cur = _current(s)
        years = _years(s)
    assert pub["changed"] == ["2027-12-24"]
    assert proj_out["years"] == 1 and proj_out["retired_for_published_years"] == 1  # Good Friday 2027
    assert date(2027, 3, 26) not in cur and cur[date(2027, 12, 24)][:2] == ("early_close", time(13, 0))
    assert years[2027] == "X-PAGE" and years[2028] == "X-PROJ"
    with db.session() as s:
        again = golden.build(s, X, {"X-PAGE": page2, "X-PROJ": proj})["sources"][2]
    assert again["added"] == 0 and "retired_for_published_years" not in again


def test_a_published_day_matching_the_projection_survives_the_handover(migrated_db):
    gf = _closed(2027, 3, 26, "Good Friday")
    proj = _state("X-PROJ", [2026, 2027], [_closed(2026, 1, 1, "New Year's Day"), gf])
    page = _state("X-PAGE", [2026], [_closed(2026, 1, 1, "New Year's Day")])
    with db.session() as s:
        golden.build(s, X, {"X-PAGE": page, "X-PROJ": proj})
    page2 = _state("X-PAGE", [2026, 2027], [_closed(2026, 1, 1, "New Year's Day"), gf], capture=2)
    for taken in (1, None):  # the handover, then a later build that must leave it alone
        with db.session() as s:
            pub, _, proj_out = golden.build(s, X, {"X-PAGE": page2, "X-PROJ": proj})["sources"]
            cur = _current(s)
        assert pub.get("taken_from_lower_source") == taken and pub["added"] == 0
        assert cur[date(2027, 3, 26)] == ("closed", None, "Good Friday", "X-PAGE")
        assert "retired_for_published_years" not in proj_out


def test_lineage_keeps_mkt_datas_capture_ids(migrated_db):
    page = _state("X-PAGE", [2026], [_closed(2026, 1, 1)], capture=42)
    with db.session() as s:
        golden.build(s, X, {"X-PAGE": page})
        row = s.scalar(select(CalendarDay))
        year = s.scalar(select(CalendarYear))
    assert row.capture_id == 42 and year.capture_id == 42
