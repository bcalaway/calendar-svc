"""What the Calendars screen reads (mkt-data's docs/phase-3.md, step 8): sources, a day's history, disagreements."""

from datetime import date

import pytest

from app import db
from app.calendars import definitions, service
from app.calendars.definitions import CalendarDef, SourceDef
from tests.test_load import _fetch, _rows

Y = CalendarDef("Y", "test", "America/New_York",
                (SourceDef("Y-PAGE"), SourceDef("Y-RULES", "rules"), SourceDef("Y-PROJ", "projected")))
PAGE = _rows("Y-PAGE", [2026], [
    ("2026-04-03", "early_close", "12:00", "Good Friday", ""),
    ("2026-10-12", "closed", "", "Columbus Day", ""),
    ("2026-11-26", "closed", "", "Thanksgiving Day", ""),
])
# The rules file disagrees with the page: Good Friday a full close, Columbus Day open (not listed), an early close at
# another time, Thanksgiving under another name, and a close the page doesn't have.
RULES = _rows("Y-RULES", [2026, 2027], [
    ("2026-04-03", "closed", "", "Good Friday", ""),
    ("2026-11-26", "closed", "", "Thanksgiving", ""),
    ("2026-11-27", "early_close", "14:00", "Day after Thanksgiving", ""),
    ("2027-01-01", "closed", "", "New Year's Day", ""),
])
PROJ = _rows("Y-PROJ", [2026, 2027, 2028], [("2028-01-03", "closed", "", "New Year's Day (observed)", "")])
STATES = {"Y-PAGE": PAGE, "Y-RULES": RULES, "Y-PROJ": PROJ}


@pytest.fixture
def loaded(migrated_db, monkeypatch):
    monkeypatch.setattr(definitions, "CALENDARS", {"Y": Y})
    monkeypatch.setattr(service, "CALENDARS", {"Y": Y})
    with db.session() as s:
        service.run_load(s, _fetch(STATES))


def test_sources_in_precedence_order(loaded):
    with db.session() as s:
        got = service.sources(s, "Y")
        with pytest.raises(service.UnknownCalendar):
            service.sources(s, "NOPE")
    assert [(x["name"], x["kind"], x["rank"], x["years"], x["first_year"], x["last_year"]) for x in got] == [
        ("Y-PAGE", "published", 1, 1, 2026, 2026), ("Y-RULES", "rules", 2, 1, 2027, 2027),
        ("Y-PROJ", "projected", 3, 1, 2028, 2028)]


def test_closes_say_which_source_decided(loaded):
    with db.session() as s:
        got = {c["date"]: c["source"] for c in service.closes(s, "Y", date(2026, 1, 1), date(2027, 12, 31))}
    assert got["2026-04-03"] == "Y-PAGE" and got["2026-11-27"] == "Y-RULES" and got["2027-01-01"] == "Y-RULES"


def test_a_days_history(loaded):
    changed = _rows("Y-PAGE", [2026], [
        ("2026-04-03", "closed", "", "Good Friday", ""),  # the page changes its mind
        ("2026-10-12", "closed", "", "Columbus Day", ""),
        ("2026-11-26", "closed", "", "Thanksgiving Day", ""),
    ], capture=9)
    with db.session() as s:
        service.run_load(s, _fetch(STATES | {"Y-PAGE": changed}))
        got = service.day_history(s, "Y", date(2026, 4, 3))
        assert service.day_history(s, "Y", date(2026, 4, 6)) == []  # always open
    assert [(v["status"], v["close_time"], v["capture_id"], bool(v["valid_to"])) for v in got] == [
        ("early_close", "12:00", 7, True), ("closed", "", 9, False)]


def test_disagreements(loaded):
    asked = []

    def fetch(names):
        asked.append(names)
        return _fetch(STATES)(names)

    with db.session() as s:
        got = service.disagreements(s, "Y", fetch)
    assert asked == [["Y-PAGE", "Y-RULES"]]  # never the projection
    assert [(d["date"], d["source"], d["differs"], d["source_says"], d["calendar_says"], d["decided_by"])
            for d in got] == [
        ("2026-04-03", "Y-RULES", "status", "closed", "early_close 12:00", "Y-PAGE"),
        ("2026-10-12", "Y-RULES", "status", "open", "closed", "Y-PAGE"),
        ("2026-11-26", "Y-RULES", "name", "closed", "closed", "Y-PAGE"),
        # The page covers 2026 and leaves the day after Thanksgiving open, but the rules' early close is in the
        # calendar: a lower source decided a day a higher one covers.
        ("2026-11-27", "Y-PAGE", "status", "open", "early_close 14:00", "Y-RULES"),
    ]
    assert [d["decided_by_higher"] for d in got] == [True, True, True, False]
