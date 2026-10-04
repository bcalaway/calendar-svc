"""The answers calendar-svc gives: business days, closes, and the calendar metrics."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import db, jobs
from app.calendars import definitions, service
from app.calendars.definitions import CalendarDef, SourceDef
from app.config import Settings
from app.main import app
from app.metrics import render
from tests.test_load import _fetch, _rows

X = CalendarDef("X", "test", "America/New_York", (SourceDef("X-PUB"), SourceDef("X-PROJ", "projected")), next_year_due=(12, 20))
PUB = _rows("X-PUB", [2026], [
    ("2026-04-03", "early_close", "12:00", "Good Friday", ""),
    ("2026-12-25", "closed", "", "Christmas Day", ""),
])
PROJ = _rows("X-PROJ", [2026, 2027, 2029], [
    ("2027-03-26", "closed", "", "Good Friday", ""),
    ("2029-12-25", "closed", "", "Christmas Day", ""),
])


@pytest.fixture
def loaded(migrated_db, monkeypatch):
    monkeypatch.setattr(definitions, "CALENDARS", {"X": X})
    monkeypatch.setattr(service, "CALENDARS", {"X": X})
    from app import metrics

    monkeypatch.setattr(metrics, "CALENDARS", {"X": X})
    with db.session() as s:
        service.run_load(s, _fetch({"X-PUB": PUB, "X-PROJ": PROJ}))


def _bd(day):
    with db.session() as s:
        return service.business_day(s, "X", day)


def test_business_day_answers(loaded):
    assert _bd(date(2026, 4, 4)) == {"calendar": "X", "date": "2026-04-04", "business_day": False, "status": "weekend"}
    assert _bd(date(2026, 4, 3)) == {
        "calendar": "X", "date": "2026-04-03", "business_day": True, "status": "early_close",
        "holiday": "Good Friday", "close_time": "12:00",
    }
    assert _bd(date(2026, 12, 25))["business_day"] is False and "projected" not in _bd(date(2026, 12, 25))
    assert _bd(date(2026, 12, 24)) == {"calendar": "X", "date": "2026-12-24", "business_day": True, "status": "open"}
    projected = _bd(date(2027, 3, 26))
    assert projected["projected"] is True and projected["business_day"] is False
    with pytest.raises(service.NotCovered):
        _bd(date(2028, 1, 4))
    with db.session() as s, pytest.raises(service.UnknownCalendar):
        service.business_day(s, "NOPE", date(2026, 1, 2))


def test_closes_in_a_range(loaded):
    with db.session() as s:
        rows = service.closes(s, "X", date(2026, 1, 1), date(2027, 12, 31))
    assert [(r["date"], r["status"], r["close_time"], r["projected"]) for r in rows] == [
        ("2026-04-03", "early_close", "12:00", False),
        ("2026-12-25", "closed", "", False),
        ("2027-03-26", "closed", "", True),
    ]


def test_calendar_metrics(loaded):
    with db.session() as s:
        text = render(s, today=date(2026, 10, 4))
    assert 'calendar_svc_calendar_years{calendar="X",kind="published"} 1' in text
    assert 'calendar_svc_calendar_years{calendar="X",kind="projected"} 2' in text
    assert 'calendar_svc_calendar_gap_years{calendar="X"} 1' in text  # 2028
    assert 'calendar_svc_calendar_gap_year{calendar="X",year="2028"} 1' in text
    assert 'calendar_svc_calendar_days{calendar="X",status="early_close"} 1' in text
    # Next year (2027) is only projected: not published; not yet overdue before Dec 20.
    assert 'calendar_svc_calendar_next_year_published{calendar="X",year="2027"} 0' in text
    assert 'calendar_svc_calendar_next_year_overdue{calendar="X",year="2027"} 0' in text
    assert 'holiday="Christmas Day",status="closed",close_time="",projected="no"} 82' in text
    with db.session() as s:
        late = render(s, today=date(2026, 12, 21))
    assert 'calendar_svc_calendar_next_year_overdue{calendar="X",year="2027"} 1' in late


client = TestClient(app)


def test_business_day_over_http(loaded, monkeypatch):
    monkeypatch.setattr(jobs, "settings", Settings(airflow_token="a", read_token="r"))
    ok = client.get("/jobs/calendars/x/business-day?on=2026-04-03", headers={"Authorization": "Bearer r"})
    assert ok.status_code == 200 and ok.json()["status"] == "early_close"
    assert client.get("/jobs/calendars/X/business-day?on=2028-01-04", headers={"Authorization": "Bearer a"}).status_code == 409
    assert client.get("/jobs/calendars/NOPE/business-day?on=2026-01-02", headers={"Authorization": "Bearer a"}).status_code == 404
    assert client.get("/jobs/calendars/X/business-day?on=2026-04-03").status_code == 401
    # The read token only reads.
    assert client.post("/jobs/load", headers={"Authorization": "Bearer r"}).status_code == 401


def test_closes_over_http(loaded, monkeypatch):
    monkeypatch.setattr(jobs, "settings", Settings(airflow_token="a"))
    r = client.get("/jobs/calendars/X/closes?start=2026-01-01&end=2026-12-31", headers={"Authorization": "Bearer a"})
    assert r.status_code == 200 and [c["date"] for c in r.json()["closes"]] == ["2026-04-03", "2026-12-25"]


def test_coverage(loaded):
    with db.session() as s:
        rows = service.coverage(s, "X")
    assert rows == [
        {"year": 2026, "source": "X-PUB", "kind": "published"},
        {"year": 2027, "source": "X-PROJ", "kind": "projected"},
        {"year": 2029, "source": "X-PROJ", "kind": "projected"},
    ]
