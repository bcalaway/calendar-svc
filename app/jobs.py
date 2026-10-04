"""Job API for Airflow (ADR-0031 in nyc_pa_aws_gitops).

Airflow's DAGs call these over the home-platform network; the work runs in
this container. Every endpoint requires `Authorization: Bearer
<AIRFLOW_TOKEN>` (other apps share the network), is idempotent (Airflow
retries) and answers with a JSON summary that shows in the task log. A
failure is a 502 with the reason.

The GET endpoints only read, and also accept READ_TOKEN (home-mcp's). The
business-day answer is what DAGs' short-circuit first task asks; it answers
409 for a year no source covers.
"""

import hmac
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query

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


def require_read_token(authorization: str | None = Header(default=None)) -> None:
    """The Airflow token, or the read-only token. For GET endpoints only."""
    tokens = [t for t in (settings.airflow_token, settings.read_token) if t]
    if not tokens:
        raise HTTPException(503, "job API disabled: no AIRFLOW_TOKEN or READ_TOKEN set")
    given = (authorization or "").removeprefix("Bearer ").strip().encode()
    # Compare against every token (no early exit), so timing doesn't say which matched.
    matches = [hmac.compare_digest(given, t.encode()) for t in tokens]
    if not any(matches):
        raise HTTPException(401, "bad or missing token")


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


@router.get("/calendars/{name}/business-day", dependencies=[Depends(require_read_token)])
def business_day(name: str, on: date) -> dict:
    """Is `on` a business day for this calendar? (`projected: true` from a year no publisher covers yet.)"""
    try:
        with db.session() as s:
            return service.business_day(s, name.upper(), on)
    except service.UnknownCalendar as e:
        raise HTTPException(404, str(e)) from None
    except service.NotCovered as e:
        raise HTTPException(409, str(e)) from None


@router.get("/calendars/{name}/closes", dependencies=[Depends(require_read_token)])
def closes(name: str, start: date, end: date | None = None, limit: int = Query(500, ge=1, le=5000)) -> dict:
    """Closed and early-close weekdays from start to end (default: a year after start)."""
    end = end or start + timedelta(days=365)
    try:
        with db.session() as s:
            rows = service.closes(s, name.upper(), start, end)
    except service.UnknownCalendar as e:
        raise HTTPException(404, str(e)) from None
    return {"calendar": name.upper(), "start": start.isoformat(), "end": end.isoformat(),
            "truncated": len(rows) > limit, "closes": rows[:limit]}
