import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.modules.notifications.application.dtos import PushMessage, PushResult
from app.modules.notifications.application.errors import PushProviderUnavailableError
from app.modules.notifications.application.push import PushDispatchService
from app.modules.notifications.domain.content import content
from app.modules.notifications.domain.models import PushDeliveryStatus as S
from app.modules.notifications.domain.models import PushResultKind
from app.modules.notifications.infrastructure.push_gateway import (
    ConfiguredPushGatewayRegistry,
    UnconfiguredPushGateway,
)
from tests.modules.notifications.fakes import (
    MemoryPushRepository,
    device,
    enqueue,
    notification,
)

pytestmark = pytest.mark.anyio


def configured(setup, result=None):
    d = device(setup.customer.customer_id)
    setup.store.devices[d.id] = d
    n = notification(setup.customer.customer_id)
    enqueue(setup.store, n)
    repo = MemoryPushRepository(setup.store)
    if result is not None:
        setup.gateway.result = result
    return d, n, repo, PushDispatchService(repo, setup.registry, clock=setup.clock)


async def test_no_gateway_fails_before_claim_even_when_outbox_empty(setup):
    repo = MemoryPushRepository(setup.store)
    service = PushDispatchService(repo, ConfiguredPushGatewayRegistry())
    with pytest.raises(PushProviderUnavailableError):
        await service.dispatch_pending_pushes()
    assert repo.claim_calls == 0


async def test_sent_outside_transaction_same_inapp_content_safe_data_idempotent(setup):
    d, n, repo, service = configured(setup)

    async def verify(message):
        assert not repo.in_transaction and not setup.store.mutex.locked()
        assert message.token == d.push_token
        assert message.title == content(n.kind, n.order_number_snapshot).title
        assert message.body == content(n.kind, n.order_number_snapshot).body
        assert set(message.data) == {"order_id", "order_number", "kind", "status"}
        assert message.provider_idempotency_key.startswith("push-delivery:")
        assert d.push_token not in repr(message)

    setup.gateway.hook = verify
    result = await service.dispatch_pending_pushes()
    assert result.claimed == result.sent == 1
    assert await service.dispatch_pending_pushes() == replace(result, claimed=0, sent=0)
    p = next(iter(setup.store.deliveries.values()))
    assert p.status == S.SENT and p.sent_at == setup.clock() and p.attempt_count == 1


@pytest.mark.parametrize(
    "result",
    [
        PushResult(kind=PushResultKind.RETRYABLE_FAILURE),
        OSError("private-provider-detail"),
        TimeoutError("test-timeout"),
        object(),
    ],
)
async def test_transient_failure_safe_backoff_not_sent(setup, result):
    d, n, repo, service = configured(setup, result)
    first = await service.dispatch_pending_pushes()
    assert first.pending == 1 and first.sent == 0
    p = next(iter(setup.store.deliveries.values()))
    assert p.next_attempt_at == setup.clock() + timedelta(seconds=30)
    assert p.failure_code == "RETRYABLE_FAILURE"
    assert (await service.dispatch_pending_pushes()).claimed == 0
    assert setup.store.devices[d.id].is_active


async def test_five_attempts_no_sixth_then_terminal(setup):
    d, n, repo, service = configured(
        setup, PushResult(kind=PushResultKind.RETRYABLE_FAILURE)
    )
    for attempt in range(1, 6):
        result = await service.dispatch_pending_pushes()
        p = next(iter(setup.store.deliveries.values()))
        assert p.attempt_count == attempt
        if attempt < 5:
            assert result.pending == 1
            setup.clock.now = p.next_attempt_at
        else:
            assert result.failed == 1 and p.status == S.FAILED
    assert (await service.dispatch_pending_pushes()).claimed == 0
    assert len(setup.gateway.messages) == 5


async def test_invalid_token_disables_and_cancels_remaining_keeps_privacy_lease(setup):
    d, n, repo, service = configured(
        setup,
        PushResult(
            kind=PushResultKind.INVALID_TOKEN,
            provider_message_id="discard-private-adapter-response",
        ),
    )
    enqueue(setup.store, notification(n.customer_id, sequence=2))
    result = await service.dispatch_pending_pushes(limit=1)
    assert result.failed == 1
    current = setup.store.devices[d.id]
    assert not current.is_active and current.generation == d.generation + 1
    assert current.send_locked_until > setup.clock()
    assert sorted(p.status for p in setup.store.deliveries.values()) == [
        S.CANCELLED,
        S.FAILED,
    ]
    assert all(p.provider_message_id is None for p in setup.store.deliveries.values())


async def test_permanent_failure_does_not_disable_device(setup):
    d, n, repo, service = configured(
        setup, PushResult(kind=PushResultKind.PERMANENT_FAILURE)
    )
    assert (await service.dispatch_pending_pushes()).failed == 1
    assert setup.store.devices[d.id].is_active


async def test_crash_lease_expiry_recovers_and_old_worker_cannot_complete(setup):
    d, n, repo, service = configured(setup)
    first = (await repo.claim(["test"], setup.clock(), 1))[0]
    assert await repo.claim(["test"], setup.clock(), 1) == []
    setup.clock.advance(121)
    second = (await repo.claim(["test"], setup.clock(), 1))[0]
    assert second.delivery.attempt_count == 2
    assert second.delivery.claim_token != first.delivery.claim_token
    assert (
        await repo.complete(first, PushResult(kind=PushResultKind.SENT), setup.clock())
        is None
    )
    assert (
        await repo.complete(second, PushResult(kind=PushResultKind.SENT), setup.clock())
        == S.SENT
    )


async def test_expired_fifth_processing_fails_without_extra_network_send(setup):
    d, n, repo, service = configured(setup)
    p = next(iter(setup.store.deliveries.values()))
    setup.store.deliveries[p.id] = replace(p, attempt_count=4)
    claim = (await repo.claim(["test"], setup.clock(), 1))[0]
    assert claim.delivery.attempt_count == 5
    setup.clock.advance(121)
    assert (await service.dispatch_pending_pushes()).claimed == 0
    assert setup.store.deliveries[p.id].status == S.FAILED
    assert not setup.gateway.messages


async def test_delete_between_claim_and_send_is_fenced(setup):
    d, n, repo, service = configured(setup)
    claim = (await repo.claim(["test"], setup.clock(), 1))[0]
    await setup.service.unregister_device(setup.customer, d.installation_id)
    assert not await repo.can_send(claim, setup.clock())
    assert (
        await repo.complete(
            claim, PushResult(kind=PushResultKind.INVALID_TOKEN), setup.clock()
        )
        is None
    )


async def test_memory_concurrent_dispatches_never_claim_same_delivery(setup):
    d, n, repo, service = configured(setup)
    values = await asyncio.gather(
        service.dispatch_pending_pushes(), service.dispatch_pending_pushes()
    )
    assert sum(r.sent for r in values) == 1 and len(setup.gateway.messages) == 1


async def test_unexpected_adapter_failure_leaves_recoverable_lease(setup):
    d, n, repo, service = configured(
        setup, RuntimeError("test-adapter-programming-error")
    )
    with pytest.raises(RuntimeError):
        await service.dispatch_pending_pushes()
    assert next(iter(setup.store.deliveries.values())).status == S.PROCESSING


async def test_external_retry_uses_stable_delivery_key(setup):
    d, n, repo, service = configured(
        setup, PushResult(kind=PushResultKind.RETRYABLE_FAILURE)
    )
    await service.dispatch_pending_pushes()
    setup.clock.advance(30)
    setup.gateway.result = PushResult(kind=PushResultKind.SENT)
    await service.dispatch_pending_pushes()
    assert setup.gateway.messages[0].provider_idempotency_key == (
        setup.gateway.messages[1].provider_idempotency_key
    )


def test_unconfigured_gateway_never_advertised_or_fake_success():
    registry = ConfiguredPushGatewayRegistry()
    assert registry.provider_codes() == ()
    with pytest.raises(PushProviderUnavailableError):
        registry.resolve("fcm")
    with pytest.raises(ValueError):
        ConfiguredPushGatewayRegistry([UnconfiguredPushGateway()])


def test_push_message_repr_redacts_token():
    from uuid import uuid4

    message = PushMessage(
        delivery_id=uuid4(),
        notification_id=uuid4(),
        token="private-test-token",
        title="Test",
        body="Test",
        data={},
        provider_idempotency_key="test",
    )
    assert "private-test-token" not in repr(message)


async def test_provider_call_timeout_retries_before_lease_expires(setup):
    d, n, repo, _ = configured(setup)
    cancelled = asyncio.Event()

    async def hang(message):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    setup.gateway.hook = hang
    service = PushDispatchService(
        repo, setup.registry, clock=setup.clock, timeout_seconds=0.001
    )
    assert (await service.dispatch_pending_pushes()).pending == 1
    assert cancelled.is_set()
    assert next(iter(setup.store.deliveries.values())).status == S.PENDING


@pytest.mark.parametrize("seconds", [0, -1, 61, True, float("inf"), float("nan")])
def test_invalid_push_timeout_rejected_before_dispatch(setup, seconds):
    from app.shared.application.exceptions import RequestDataError

    with pytest.raises(RequestDataError):
        PushDispatchService(
            MemoryPushRepository(setup.store), setup.registry, timeout_seconds=seconds
        )
