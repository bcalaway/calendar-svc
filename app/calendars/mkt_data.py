"""Reading near-raw calendar rows from mkt-data (CalendarSources, gRPC).

mkt-data serves each calendar source's rows as that source states them
(proto/calendar_sources.proto, copied from mkt-data). `fetch_states` reads
every source the calendars here name and turns each into a SourceState for
golden.build. Calendars are a few thousand rows, so each source is read whole.
"""

from datetime import date, time

from app.calendars.golden import SourceState
from app.calendars.parsed import Day

TIMEOUT_SECONDS = 60


def state_from_rows(name: str, years, days) -> SourceState:
    """A SourceState from GetSource's years and current days (messages or anything shaped like them)."""
    out = SourceState(name, years={int(y.year): int(y.capture_id) for y in years})
    for d in days:
        if d.valid_to:  # superseded: history stays in mkt-data
            continue
        day = Day(date.fromisoformat(d.day), d.status, d.holiday, time.fromisoformat(d.close_time) if d.close_time else None)
        out.days[day.day] = (day, int(d.capture_id))
    return out


def fetch_states(target: str, names: list[str]) -> tuple[dict[str, SourceState], list[dict]]:
    """Every named source's current rows from mkt-data, plus what ListSources says about each."""
    import grpc  # here, so the rest of the app (and its tests) runs without compiled grpcio

    from app.grpc_gen import calendar_sources_pb2 as pb
    from app.grpc_gen import calendar_sources_pb2_grpc as pb_grpc

    with grpc.insecure_channel(target) as channel:
        stub = pb_grpc.CalendarSourcesStub(channel)
        listed = {x.name: x for x in stub.ListSources(pb.ListSourcesRequest(), timeout=TIMEOUT_SECONDS).sources}
        states, info = {}, []
        for name in names:
            src = listed.get(name)
            if src is None:
                info.append({"source": name, "note": "mkt-data doesn't list this source"})
                continue
            info.append({"source": name, "parsed": src.parsed, "latest_capture_id": src.latest_capture_id,
                         "latest_applied_capture_id": src.latest_applied_capture_id})
            if not src.parsed or not src.latest_applied_capture_id:
                continue
            rows = stub.GetSource(pb.GetSourceRequest(source=name), timeout=TIMEOUT_SECONDS)
            states[name] = state_from_rows(name, rows.years, rows.days)
    return states, info
