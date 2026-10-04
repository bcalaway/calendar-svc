import asyncio

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from app.grpc_gen import calendars_pb2, calendars_pb2_grpc
from app.grpc_server import CALENDARS_SERVICE, start_grpc_server


async def _call(fn):
    # Port 0: the OS picks a free port, so tests never collide with 9090.
    server, port = await start_grpc_server(0)
    try:
        async with grpc.aio.insecure_channel(f"localhost:{port}") as channel:
            return await fn(channel)
    finally:
        await server.stop(grace=None)


def test_health_reports_serving():
    async def check(channel):
        stub = health_pb2_grpc.HealthStub(channel)
        overall = await stub.Check(health_pb2.HealthCheckRequest(service=""))
        calendars = await stub.Check(health_pb2.HealthCheckRequest(service=CALENDARS_SERVICE))
        return overall.status, calendars.status

    serving = health_pb2.HealthCheckResponse.SERVING
    assert asyncio.run(_call(check)) == (serving, serving)


def test_calendars_service(migrated_db):
    from app import db
    from app.calendars import service
    from tests.test_load import K8, _fetch

    with db.session() as s:
        service.run_load(s, _fetch({"FED-K8": K8}))

    async def ask(channel):
        stub = calendars_pb2_grpc.CalendarsStub(channel)
        listed = await stub.ListCalendars(calendars_pb2.ListCalendarsRequest())
        closed = await stub.BusinessDay(calendars_pb2.BusinessDayRequest(calendar="fed", date="2026-10-19"))
        closes = await stub.Closes(calendars_pb2.ClosesRequest(calendar="FED", start="2026-01-01", end="2026-12-31"))
        codes = []
        for req in (calendars_pb2.BusinessDayRequest(calendar="FED", date="2030-01-02"),
                    calendars_pb2.BusinessDayRequest(calendar="NOPE", date="2026-01-02"),
                    calendars_pb2.BusinessDayRequest(calendar="FED", date="tomorrow")):
            try:
                await stub.BusinessDay(req)
                codes.append(None)
            except grpc.aio.AioRpcError as e:
                codes.append(e.code())
        return listed, closed, closes, codes

    listed, closed, closes, codes = asyncio.run(_call(ask))
    fed = next(c for c in listed.calendars if c.name == "FED")
    assert (fed.first_year, fed.last_year, fed.timezone) == (2026, 2026, "America/New_York")
    assert closed.business_day is False and closed.status == "closed" and closed.holiday == "Columbus Day"
    assert [c.date for c in closes.closes] == ["2026-01-01", "2026-10-19"]
    assert codes == [grpc.StatusCode.OUT_OF_RANGE, grpc.StatusCode.NOT_FOUND, grpc.StatusCode.INVALID_ARGUMENT]


def test_fetch_states_reads_mkt_datas_calendar_sources():
    """The client against a stand-in for mkt-data's CalendarSources (runs in CI, which has grpcio)."""
    from concurrent import futures
    from datetime import date

    from app.calendars import mkt_data
    from app.grpc_gen import calendar_sources_pb2 as pb
    from app.grpc_gen import calendar_sources_pb2_grpc as pb_grpc

    class FakeMktData(pb_grpc.CalendarSourcesServicer):
        def ListSources(self, request, context):
            return pb.ListSourcesResponse(sources=[
                pb.SourceInfo(name="FED-K8", calendar="FED", parsed=True, latest_capture_id=3, latest_applied_capture_id=3),
                pb.SourceInfo(name="SIFMA-US-HISTORY", calendar="SIFMA-US", parsed=False),
            ])

        def GetSource(self, request, context):
            assert request.source == "FED-K8"
            return pb.SourceRows(
                source=pb.SourceInfo(name="FED-K8"),
                years=[pb.SourceYear(year=2026, capture_id=3)],
                days=[pb.SourceDay(day="2026-01-01", status="closed", holiday="New Year's Day", capture_id=3)],
            )

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    pb_grpc.add_CalendarSourcesServicer_to_server(FakeMktData(), server)
    port = server.add_insecure_port("localhost:0")
    server.start()
    try:
        states, info = mkt_data.fetch_states(f"localhost:{port}", ["FED-K8", "SIFMA-US-HISTORY", "NYSE-HOURS"])
    finally:
        server.stop(grace=None)
    assert list(states) == ["FED-K8"] and list(states["FED-K8"].days) == [date(2026, 1, 1)]
    assert info[2] == {"source": "NYSE-HOURS", "note": "mkt-data doesn't list this source"}
