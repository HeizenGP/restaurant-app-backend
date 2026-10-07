import asyncio
from datetime import timedelta

import pytest

from app.modules.notifications.application.dtos import StreamScope
from app.modules.notifications.application.errors import RealtimePermissionError
from app.modules.notifications.application.realtime import RealtimeStreamService
from app.modules.notifications.presentation.sse import encode_frame, resume_cursor
from app.shared.application.exceptions import RequestDataError
from tests.modules.notifications.fakes import (
    MemoryStreamReader,
    enqueue,
    event,
    notification,
)

pytestmark = pytest.mark.anyio


def configured(setup, branch=False, who="customer"):
    p = getattr(setup, who)
    scope = StreamScope(
        principal=p,
        credential="test-not-a-real-jwt",
        branch_id=setup.branch if branch else None,
        permission="ORDER_REALTIME_VIEW" if branch else None,
    )
    reader = MemoryStreamReader(setup.repo, clock=setup.clock)
    service = RealtimeStreamService(
        reader,
        clock=setup.clock,
        monotonic=setup.clock.monotonic,
        sleep=setup.clock.sleep,
    )
    return scope, reader, service


async def connected():
    return False


async def test_no_cursor_starts_at_scoped_committed_max_not_global_history(setup):
    enqueue(setup.store, notification(setup.customer.customer_id, sequence=3))
    enqueue(setup.store, notification(setup.foreign.customer_id, sequence=99))
    scope, reader, service = configured(setup)
    prepared = await service.prepare(scope)
    stream = service.stream(scope, prepared, connected)
    ready = await anext(stream)
    assert ready.id == 3 and ready.data["resync_required"]
    n = notification(setup.customer.customer_id, sequence=100)
    enqueue(setup.store, n)
    frame = await anext(stream)
    assert frame.id == 100 and frame.event == "notification.created"
    assert n.id.hex not in str(ready.data)
    await stream.aclose()


async def test_replay_ready_keeps_resume_id_and_events_ordered_despite_gaps(setup):
    for i in [2, 5, 10]:
        enqueue(setup.store, notification(setup.customer.customer_id, sequence=i))
    scope, reader, service = configured(setup)
    prepared = await service.prepare(scope, 2)
    stream = service.stream(scope, prepared, connected)
    ready = await anext(stream)
    assert ready.id == 2 and not ready.data["resync_required"]
    assert ready.data["latest_event_id"] == 10
    assert [(await anext(stream)).id for _ in range(2)] == [5, 10]
    await stream.aclose()


async def test_more_than_one_batch_drains_without_waiting(setup):
    for i in range(1, 202):
        enqueue(setup.store, notification(setup.customer.customer_id, sequence=i))
    scope, reader, service = configured(setup)
    stream = service.stream(scope, await service.prepare(scope, 0), connected)
    assert (await anext(stream)).event == "ready"
    assert [(await anext(stream)).id for _ in range(201)] == list(range(1, 202))
    assert setup.clock.elapsed == 0
    assert len(reader.calls) == 3
    await stream.aclose()


async def test_heartbeats_and_permission_recheck_every_fifteen_seconds(setup):
    scope, reader, service = configured(setup)
    stream = service.stream(scope, await service.prepare(scope), connected)
    await anext(stream)
    frame = await anext(stream)
    assert frame.comment == "keep-alive" and setup.clock.elapsed == 15
    assert sum(c[2] for c in reader.calls) >= 2
    reader.revoked = True
    assert (
        await anext(stream)
    ).comment == "stream closed; reconnect with last event id"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_slow_consumer_revalidates_inside_initial_batch_before_next_row(setup):
    for i in range(1, 4):
        enqueue(setup.store, notification(setup.customer.customer_id, sequence=i))
    scope, reader, service = configured(setup)
    stream = service.stream(scope, await service.prepare(scope, 0), connected)
    await anext(stream)
    assert (await anext(stream)).id == 1
    setup.clock.advance(16)
    reader.revoked = True
    assert (await anext(stream)).comment is not None
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert reader.calls[-1] == (None, 1, True)


async def test_exact_jwt_expiry_even_before_periodic_recheck(setup):
    enqueue(setup.store, notification(setup.customer.customer_id, sequence=1))
    scope, reader, service = configured(setup)
    reader.expires_at = setup.clock() + timedelta(seconds=2)
    stream = service.stream(scope, await service.prepare(scope, 0), connected)
    await anext(stream)
    setup.clock.advance(2)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_max_lifetime_no_events_and_disconnection(setup):
    scope, reader, service = configured(setup)
    stream = service.stream(scope, await service.prepare(scope), connected)
    frames = [f async for f in stream]
    assert frames[0].event == "ready"
    assert setup.clock.elapsed == 300
    assert all(f.comment == "keep-alive" for f in frames[1:])

    async def disconnected():
        return True

    stream = service.stream(scope, await service.prepare(scope), disconnected)
    assert len([f async for f in stream]) == 1


async def test_cancellation_propagates_not_swallowed_as_provider_error(setup):
    scope, reader, service = configured(setup)

    async def cancel(_):
        raise asyncio.CancelledError()

    service.sleep = cancel
    stream = service.stream(scope, await service.prepare(scope), connected)
    await anext(stream)
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)


@pytest.mark.parametrize(
    "type_,name",
    [
        ("ORDER_CREATED", "order.created"),
        ("ORDER_CHANGED", "order.changed"),
        ("DELIVERY_DELAYED", "delivery.delayed"),
    ],
)
async def test_branch_event_types_safe_and_scoped(setup, type_, name):
    from app.modules.notifications.domain.models import RealtimeEventType

    e = event(setup.branch, event_type=RealtimeEventType(type_))
    setup.store.events[e.id] = e
    setup.store.events[99] = event(setup.other_branch, 99)
    scope, reader, service = configured(setup, branch=True, who="admin")
    stream = service.stream(scope, await service.prepare(scope, 0), connected)
    await anext(stream)
    frame = await anext(stream)
    assert frame.event == name and frame.id == 1
    encoded = encode_frame(frame)
    assert "text/event-stream" not in encoded
    assert "customer" not in encoded and "source_reference_id" not in encoded
    await stream.aclose()


async def test_preflight_auth_error_is_http_not_started_stream(setup):
    scope, reader, service = configured(setup)
    reader.revoked = True
    with pytest.raises(RealtimePermissionError):
        await service.prepare(scope)


@pytest.mark.parametrize(
    "header", ["-1", "1.2", "a", "９", "1\n2", "9223372036854775808"]
)
def test_header_cursor_invalid(header):
    with pytest.raises(RequestDataError):
        resume_cursor(None, header)


@pytest.mark.parametrize("value", [0, 1, 9223372036854775807])
def test_header_cursor_valid_and_explicit_wins(value):
    assert resume_cursor(None, str(value)) == value
    assert resume_cursor(value, "ignored-invalid") == value


def test_header_absent_distinct_from_explicit_zero():
    assert resume_cursor(None, None) is None
    assert resume_cursor(None, "0") == 0
