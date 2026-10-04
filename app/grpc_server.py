"""gRPC server (ADR-0020): calendar-svc's service-to-service API.

Internal-only: listens on GRPC_PORT (9090 by convention), plaintext, reachable
only by other containers on the `home-platform` Docker network at
`calendar-svc:9090`. Never routed through Traefik. Runs in the same process
and event loop as the FastAPI app (started from its lifespan in app/main.py).

Serves `calendar_svc.Calendars` (proto/calendars.proto): the golden
calendars' business-day answer and closes, for other services (quote-svc's
missing-day checks, payment schedules later). Also the standard
grpc.health.v1.Health service.
"""

import asyncio
from datetime import date

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from sqlalchemy import select

from app import db
from app.calendars import service
from app.calendars.definitions import CALENDARS as CALENDAR_DEFS
from app.grpc_gen import calendars_pb2, calendars_pb2_grpc
from app.models import Calendar, CalendarYear

CALENDARS_SERVICE = calendars_pb2.DESCRIPTOR.services_by_name["Calendars"].full_name


def _list() -> calendars_pb2.ListCalendarsResponse:
    out = []
    with db.session() as s:
        ids = {c.name: c.id for c in s.scalars(select(Calendar))}
        for name, d in CALENDAR_DEFS.items():
            ys = s.scalars(select(CalendarYear.year).where(CalendarYear.calendar_id == ids[name])).all() if name in ids else []
            out.append(calendars_pb2.CalendarInfo(
                name=name, description=d.description, timezone=d.timezone,
                first_year=min(ys, default=0), last_year=max(ys, default=0),
            ))
    return calendars_pb2.ListCalendarsResponse(calendars=out)


def _business_day(name: str, day: date) -> calendars_pb2.BusinessDayResponse:
    with db.session() as s:
        r = service.business_day(s, name, day)
    return calendars_pb2.BusinessDayResponse(
        calendar=r["calendar"], date=r["date"], business_day=r["business_day"], status=r["status"],
        holiday=r.get("holiday", ""), close_time=r.get("close_time", ""), projected=r.get("projected", False),
    )


def _closes(name: str, start: date, end: date) -> calendars_pb2.ClosesResponse:
    with db.session() as s:
        rows = service.closes(s, name, start, end)
    return calendars_pb2.ClosesResponse(calendar=name, closes=[
        calendars_pb2.Close(date=r["date"], status=r["status"], holiday=r["holiday"], close_time=r["close_time"],
                            projected=r["projected"])
        for r in rows
    ])


def _date(value: str) -> date:
    return date.fromisoformat(value)


class Calendars(calendars_pb2_grpc.CalendarsServicer):
    # Method names come from the proto, hence not snake_case. The database
    # work is synchronous SQLAlchemy, so it runs in a thread.
    async def ListCalendars(self, request, context):
        return await asyncio.to_thread(_list)

    async def BusinessDay(self, request, context):
        try:
            day = _date(request.date)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, f"bad date {request.date!r}; want YYYY-MM-DD")
        try:
            return await asyncio.to_thread(_business_day, request.calendar.upper(), day)
        except service.UnknownCalendar as e:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(e))
        except service.NotCovered as e:
            await context.abort(grpc.StatusCode.OUT_OF_RANGE, str(e))

    async def Closes(self, request, context):
        try:
            start, end = _date(request.start), _date(request.end)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "start and end must be YYYY-MM-DD")
        try:
            return await asyncio.to_thread(_closes, request.calendar.upper(), start, end)
        except service.UnknownCalendar as e:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(e))


async def start_grpc_server(port: int) -> tuple[grpc.aio.Server, int]:
    """Start the server; returns it and the bound port (port 0 picks a free one)."""
    server = grpc.aio.server()
    calendars_pb2_grpc.add_CalendarsServicer_to_server(Calendars(), server)

    health_servicer = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    bound = server.add_insecure_port(f"[::]:{port}")
    await server.start()
    # "" is the overall server status; each service also reports its own.
    for svc in ("", CALENDARS_SERVICE):
        await health_servicer.set(svc, health_pb2.HealthCheckResponse.SERVING)
    return server, bound
