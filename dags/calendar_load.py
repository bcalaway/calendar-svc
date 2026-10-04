"""calendar-svc: rebuild the golden calendars from mkt-data's near-raw rows.

Runs whenever mkt-data's calendar DAGs (or its near-raw rebuild) mark the
Asset `mkt_data_calendar_sources`, so a source change reaches the golden
calendars within minutes, and nightly as a catch-up in case an event was
missed. The work runs in the calendar-svc container (POST /jobs/load); this
DAG only calls it (ADR-0031 in nyc_pa_aws_gitops). A failed run retries, and
Grafana's "Airflow task failed" alert fires if retries run out.
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airflow.sdk import Asset, AssetOrTimeSchedule, CronTriggerTimetable, dag, task

# The platform's helper lives at Airflow's DAG root (home_platform_jobs.py);
# this repo's dags/ is delivered to dags/calendar-svc/ there, so the root is
# one level up. Airflow normally has it on sys.path; this makes sure of it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from home_platform_jobs import call_app_job

# Marked by mkt-data's calendar DAGs after each successful run.
CALENDAR_SOURCES = Asset("mkt_data_calendar_sources")


@dag(
    dag_id="calendar_svc__load",
    schedule=AssetOrTimeSchedule(
        timetable=CronTriggerTimetable("41 6 * * *", timezone="UTC"),  # nightly catch-up, 06:41 UTC
        assets=[CALENDAR_SOURCES],
    ),
    start_date=datetime(2026, 10, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    default_args={"retries": 3, "retry_delay": timedelta(minutes=10)},
    tags=["calendar-svc", "calendars"],
    doc_md=__doc__,
)
def calendar_load():
    @task
    def load() -> dict:
        return call_app_job("calendar-svc", "load", timeout=600)

    load()


calendar_load()
