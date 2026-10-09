"""The load job: mkt-data's near-raw rows in, golden calendars out (app/calendars/service.py)."""

from datetime import date, time
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db, jobs
from app.calendars import mkt_data, service
from app.config import Settings
from app.main import app
from app.metrics import render
from app.models import CalendarDay, LoadRun


def _rows(name, years, days, capture=7):
    """GetSource's years and days as messages would carry them."""
    return mkt_data.state_from_rows(
        name,
        [NS(year=y, capture_id=capture, first_seen_at="") for y in years],
        [NS(day=d, status=st, close_time=t, holiday=h, capture_id=capture, valid_from="2026-10-04T00:00:00+00:00",
            valid_to=to) for d, st, t, h, to in days],
    )


K8 = _rows("FED-K8", [2026], [
    ("2026-01-01", "closed", "", "New Year's Day", ""),
    ("2026-10-12", "closed", "", "Columbus Day (old)", "2026-10-04T01:00:00+00:00"),  # superseded: skipped
    ("2026-10-19", "closed", "", "Columbus Day", ""),
])
SIFMA = _rows("SIFMA-US-HOLIDAYS", [2026], [("2026-04-03", "early_close", "12:00", "Good Friday", "")])


def _fetch(states):
    return lambda names: ({n: states[n] for n in names if n in states}, [{"source": n} for n in names])


def test_state_from_rows_keeps_current_days_and_times():
    assert sorted(K8.days) == [date(2026, 1, 1), date(2026, 10, 19)]
    day, cap = SIFMA.days[date(2026, 4, 3)]
    assert day.close_time == time(12, 0) and cap == 7 and SIFMA.years == {2026: 7}


def test_load_builds_every_calendar_and_records_the_run(migrated_db):
    with db.session() as s:
        out = service.run_load(s, _fetch({"FED-K8": K8, "SIFMA-US-HOLIDAYS": SIFMA}))
    assert [c["calendar"] for c in out["calendars"]] == ["FED", "SIFMA-US", "NYSE", "CME-IR", "GB", "TARGET", "JP", "CA", "CH", "AU", "NZ", "SE", "NO", "DK", "MX", "BR", "ZA", "PL", "CZ", "HU",
        "CL", "IL", "TR", "HK", "CN", "SG", "TH", "ID", "CME-FX"]
    with db.session() as s:
        days = s.scalars(select(CalendarDay.day).where(CalendarDay.valid_to.is_(None))).all()
        run = s.scalar(select(LoadRun))
    assert sorted(days) == [date(2026, 1, 1), date(2026, 4, 3), date(2026, 10, 19)]
    assert run.outcome == "ok"


def test_a_failed_fetch_is_recorded_and_raised(migrated_db):
    def boom(names):
        raise ConnectionError("mkt-data:9090 unreachable")

    with db.session() as s, pytest.raises(service.LoadError):
        service.run_load(s, boom)
    with db.session() as s:
        run = s.scalar(select(LoadRun))
        text = render(s)
    assert run.outcome == "error" and "unreachable" in run.detail
    assert "calendar_svc_load_ok 0" in text


def test_metrics_after_a_load(migrated_db):
    with db.session() as s:
        service.run_load(s, _fetch({"FED-K8": K8}))
        text = render(s)
    assert "calendar_svc_load_ok 1" in text
    assert 'calendar_svc_calendar_days{calendar="FED",status="closed"} 2' in text
    assert 'calendar_svc_calendar_first_year{calendar="FED",kind="published"} 2026' in text
    assert "calendar_svc_load_last_success_timestamp_seconds " in text


client = TestClient(app)


def test_load_job_needs_the_token(migrated_db, monkeypatch):
    monkeypatch.setattr(jobs, "settings", Settings(airflow_token="t"))
    monkeypatch.setattr(jobs, "_fetch", _fetch({"FED-K8": K8}))
    assert client.post("/jobs/load").status_code == 401
    r = client.post("/jobs/load", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200, r.text
    assert r.json()["calendars"][0]["calendar"] == "FED"


def test_load_job_reports_a_failure_as_502(migrated_db, monkeypatch):
    monkeypatch.setattr(jobs, "settings", Settings(airflow_token="t"))

    def boom(names):
        raise ConnectionError("nope")

    monkeypatch.setattr(jobs, "_fetch", boom)
    assert client.post("/jobs/load", headers={"Authorization": "Bearer t"}).status_code == 502


def test_metrics_endpoint_without_a_database():
    r = client.get("/metrics")
    assert r.status_code == 200 and "calendar_svc_up" in r.text
