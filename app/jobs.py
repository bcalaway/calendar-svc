"""Job API for Airflow (ADR-0031 in nyc_pa_aws_gitops).

Airflow's DAGs call these over the home-platform network; the work runs in
this container. Every endpoint requires `Authorization: Bearer
<AIRFLOW_TOKEN>` (other apps share the network), is idempotent (Airflow
retries) and answers with a JSON summary that shows in the task log. A
failure is a 502 with the reason.
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException

from app import db
from app.calendars import mkt_data, service
from app.config import settings

router = APIRouter(prefix="/jobs")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.airflow_token:
        raise HTTPException(503, "job API disabled: AIRFLOW_TOKEN isn't set")
    given = (authorization or "").removeprefix("Bearer ").strip().encode()
    if not hmac.compare_digest(given, settings.airflow_token.encode()):
        raise HTTPException(401, "bad or missing job token")


def _fetch(names):
    return mkt_data.fetch_states(settings.mkt_data_grpc, names)


@router.post("/load", dependencies=[Depends(require_token)])
def load() -> dict:
    """Rebuild every golden calendar from mkt-data's current near-raw rows."""
    try:
        with db.session() as s:
            return service.run_load(s, _fetch)
    except service.LoadError as e:
        raise HTTPException(502, f"load failed: {e}") from None
