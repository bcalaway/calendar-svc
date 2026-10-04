"""The load job: golden calendars rebuilt from mkt-data's near-raw rows.

Run by Airflow (POST /jobs/load) whenever mkt-data's calendar DAGs mark the
Asset `mkt_data_calendar_sources`, and nightly. It reads every source the
calendars name from mkt-data, then applies each calendar's sources in
precedence order (golden.build). Idempotent: the same near-raw rows change
nothing. Every run is a `load_run` row, which the metrics read.
"""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.calendars import golden
from app.calendars.definitions import CALENDARS
from app.models import LoadRun


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
