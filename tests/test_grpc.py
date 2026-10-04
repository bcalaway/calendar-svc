import asyncio

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from app.grpc_gen import example_service_pb2, example_service_pb2_grpc
from app.grpc_server import EXAMPLE_SERVICE, start_grpc_server


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
        example = await stub.Check(health_pb2.HealthCheckRequest(service=EXAMPLE_SERVICE))
        return overall.status, example.status

    serving = health_pb2.HealthCheckResponse.SERVING
    assert asyncio.run(_call(check)) == (serving, serving)


def test_ping():
    async def ping(channel):
        stub = example_service_pb2_grpc.ExampleServiceStub(channel)
        return await stub.Ping(example_service_pb2.PingRequest(message="hello"))

    assert asyncio.run(_call(ping)).message == "pong: hello"


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
