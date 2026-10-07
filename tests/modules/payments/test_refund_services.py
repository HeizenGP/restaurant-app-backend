import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.cancellations.domain.models import ReasonCode
from app.modules.orders.domain.models import OrderStatus, PaymentMethodType
from app.modules.payments.application.refund_errors import (
    RefundConflictError,
    RefundDataError,
    RefundEventPendingError,
    RefundNotFoundError,
    RefundPermissionDeniedError,
    RefundProviderUnavailableError,
    RefundWebhookAuthenticationError,
)
from app.modules.payments.domain.models import AttemptStatus, EventStatus
from app.modules.payments.domain.refunds import RefundHistorySource, RefundStatus
from app.modules.payments.infrastructure.refund_gateway import (
    UnconfiguredOnlineRefundGateway,
)
from tests.modules.cancellations.fakes import cancellation_setup
from tests.modules.payments.fakes import signed_event

pytestmark = pytest.mark.anyio


async def prepare(**kwargs):
    s = cancellation_setup(**kwargs)
    out = await s.service.cancel_order(
        s.admin, s.branch, s.order.id, ReasonCode.OUT_OF_STOCK
    )
    return s, out.refund


async def process(s, r, key="refund-key-1"):
    return await s.refund_service.process_online(s.admin, s.branch, r.id, key)


async def event(s, a, **kwargs):
    body, headers = signed_event(a, **kwargs)
    return await s.refund_service.webhook("test_gateway", body, headers)


async def test_cash_confirmation_is_separate_and_exactly_once():
    s, r = await prepare(method=PaymentMethodType.CASH)
    p = next(iter(s.db.payments.values()))
    result = await s.refund_service.confirm_cash(s.admin, s.branch, r.id)
    assert result.status == RefundStatus.REFUNDED
    assert result.refunded_at is not None
    assert await s.refund_service.confirm_cash(s.admin, s.branch, r.id) == result
    assert s.db.payments[p.id] == p
    assert s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    assert len(s.db.refund_histories) == 2
    assert s.db.refund_histories[-1].source == RefundHistorySource.STAFF
    assert not s.gateway.calls


async def test_production_gateway_unconfigured_never_marks_refunded():
    s, r = await prepare()
    s.refund_service.gateway = UnconfiguredOnlineRefundGateway()
    with pytest.raises(RefundProviderUnavailableError):
        await process(s, r)
    assert s.db.refunds[r.id] == r and not s.db.refund_attempts
    assert len(s.db.refund_histories) == 1


async def test_online_reserves_commits_calls_provider_then_persists():
    s, r = await prepare()
    original = next(iter(s.db.payments.values()))
    started = await process(s, r)
    assert started.refund.status == RefundStatus.PROCESSING
    assert started.attempt.status == AttemptStatus.PROCESSING
    request = s.gateway.calls[0]
    assert request.amount == r.amount and request.payment_id == r.payment_id
    assert request.provider_idempotency_key == "refund-attempt:" + str(
        started.attempt.id
    )
    assert (
        request.original_provider_reference
        == next(iter(s.db.attempts.values())).provider_reference
    )
    assert await process(s, r) == started and len(s.gateway.calls) == 1
    with pytest.raises(RefundConflictError):
        await process(s, r, "another-key")
    await event(s, started.attempt)
    assert s.db.refunds[r.id].status == RefundStatus.REFUNDED
    assert (
        s.db.payments[original.id] == original
        and s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    )
    assert len(s.db.refund_histories) == 3


@pytest.mark.parametrize("result", [AttemptStatus.SUCCEEDED, AttemptStatus.FAILED])
async def test_trusted_immediate_result(result):
    s, r = await prepare()
    s.gateway.result = result
    out = await process(s, r)
    assert out.refund.status == (
        RefundStatus.REFUNDED
        if result == AttemptStatus.SUCCEEDED
        else RefundStatus.FAILED
    )


async def test_timeout_retains_stable_recoverable_reservation():
    s, r = await prepare()
    s.gateway.timeout = True
    with pytest.raises(RefundProviderUnavailableError):
        await process(s, r)
    a = next(iter(s.db.refund_attempts.values()))
    assert (
        a.status == AttemptStatus.CREATED
        and s.db.refunds[r.id].status == RefundStatus.PROCESSING
    )
    s.gateway.timeout = False
    out = await process(s, r)
    assert out.attempt.id == a.id and len(s.db.refund_attempts) == 1
    assert (
        s.gateway.calls[0].provider_idempotency_key
        == s.gateway.calls[1].provider_idempotency_key
    )
    assert len(s.db.refund_histories) == 2


async def test_failed_requires_new_key_and_old_retry_does_not_send_money():
    s, r = await prepare()
    s.gateway.result = AttemptStatus.FAILED
    failed = await process(s, r)
    assert failed.refund.status == RefundStatus.FAILED
    assert await process(s, r) == failed and len(s.gateway.calls) == 1
    s.gateway.result = AttemptStatus.PROCESSING
    second = await process(s, r, "retry-new-key")
    assert second.attempt.id != failed.attempt.id
    assert len(s.db.refund_attempts) == 2 and len(s.gateway.calls) == 2
    await event(s, second.attempt)
    assert s.db.refunds[r.id].status == RefundStatus.REFUNDED


@pytest.mark.parametrize(
    "amount,currency,reason",
    [("1.00", "PEN", "AMOUNT_MISMATCH"), ("32.50", "USD", "CURRENCY_MISMATCH")],
)
async def test_verified_mismatches_are_durable_evidence_not_refunded(
    amount, currency, reason
):
    s, r = await prepare()
    out = await process(s, r)
    await event(s, out.attempt, amount=amount, currency=currency)
    stored = next(iter(s.db.refund_events.values()))
    assert (
        stored.processing_status == EventStatus.REJECTED
        and stored.reason_code == reason
    )
    assert s.db.refunds[r.id].status == RefundStatus.PROCESSING
    assert len(s.db.refund_histories) == 2


async def test_webhook_verified_before_any_database_access():
    s, r = await prepare()
    out = await process(s, r)
    body, _ = signed_event(out.attempt)
    with pytest.raises(RefundWebhookAuthenticationError):
        await s.refund_service.webhook("test_gateway", body, {})
    assert not s.db.refund_events and not s.db.mutex.locked()
    assert s.db.refunds[r.id].status == RefundStatus.PROCESSING


async def test_duplicate_event_and_changed_payload_collision():
    s, r = await prepare()
    out = await process(s, r)
    await event(s, out.attempt)
    await event(s, out.attempt)
    assert len(s.db.refund_events) == 1 and len(s.db.refund_histories) == 3
    with pytest.raises(RefundConflictError):
        await event(s, out.attempt, amount="1.00")
    assert s.db.refunds[r.id].status == RefundStatus.REFUNDED
    await event(s, out.attempt, event="new-success")
    await event(s, out.attempt, event="old-failure", result="FAILED")
    assert (
        len(s.db.refund_histories) == 3
        and not s.db.refunds[r.id].reconciliation_required
    )


async def test_unknown_reference_retained_and_retried_after_correlation():
    s, r = await prepare()
    out = await process(s, r)
    body, headers = signed_event(out.attempt, reference="late-reference")
    with pytest.raises(RefundEventPendingError):
        await s.refund_service.webhook("test_gateway", body, headers)
    assert next(iter(s.db.refund_events.values())).reason_code == "UNKNOWN_REFERENCE"
    s.db.refund_attempts[out.attempt.id] = replace(
        out.attempt, provider_reference="late-reference"
    )
    await s.refund_service.webhook("test_gateway", body, headers)
    assert s.db.refunds[r.id].status == RefundStatus.REFUNDED
    assert len(s.db.refund_events) == 1


async def test_late_success_after_failed_retry_flags_reconciliation():
    s, r = await prepare()
    s.gateway.result = AttemptStatus.FAILED
    old = await process(s, r)
    s.gateway.result = AttemptStatus.PROCESSING
    new = await process(s, r, "new-key")
    await event(s, old.attempt, event="late-old-success")
    assert s.db.refunds[r.id].status == RefundStatus.REFUNDED
    assert s.db.refunds[r.id].reconciliation_required
    await event(s, new.attempt, event="second-bank-success")
    assert (
        len([h for h in s.db.refund_histories if h.to_status == RefundStatus.REFUNDED])
        == 1
    )
    assert s.db.refund_attempts[new.attempt.id].status == AttemptStatus.SUCCEEDED


@pytest.mark.parametrize("who", ["customer", "guest", "foreign", "kitchen"])
async def test_refund_execution_requires_branch_admin(who):
    s, r = await prepare(method=PaymentMethodType.CASH)
    with pytest.raises(RefundPermissionDeniedError):
        await s.refund_service.confirm_cash(getattr(s, who), s.branch, r.id)
    assert s.db.refunds[r.id].status == RefundStatus.PENDING


async def test_owned_refund_and_branch_idor():
    s, r = await prepare()
    assert await s.refund_service.get_owned(s.customer, s.order.id) == r
    with pytest.raises(RefundNotFoundError):
        await s.refund_service.get_owned(s.foreign, s.order.id)
    b = uuid4()
    s.authz.grants.add((s.admin.user_id, b, "REFUND_MANAGE"))
    with pytest.raises(RefundNotFoundError):
        await s.refund_service.detail(s.admin, b, r.id)


@pytest.mark.parametrize("step", ["refund", "history", "audit", "commit"])
async def test_cash_failure_is_atomic(step):
    s, r = await prepare(method=PaymentMethodType.CASH)
    original_hist = list(s.db.refund_histories)
    original_audit = list(s.db.audits)
    s.unit.fail = step
    with pytest.raises(RuntimeError):
        await s.refund_service.confirm_cash(s.admin, s.branch, r.id)
    assert (
        s.db.refunds[r.id] == r
        and s.db.refund_histories == original_hist
        and s.db.audits == original_audit
    )


async def test_online_method_conflicts():
    s, r = await prepare(method=PaymentMethodType.CASH)
    with pytest.raises(RefundConflictError):
        await process(s, r)
    s, r = await prepare()
    with pytest.raises(RefundConflictError):
        await s.refund_service.confirm_cash(s.admin, s.branch, r.id)


@pytest.mark.parametrize("bad", ["none", "multiple", "provider", "amount"])
async def test_ambiguous_capture_never_calls_bank(bad):
    s, r = await prepare()
    a = next(iter(s.db.attempts.values()))
    if bad == "none":
        s.db.attempts.clear()
    elif bad == "multiple":
        extra = replace(
            a,
            id=uuid4(),
            idempotency_key="another-capture",
            provider_reference="capture-other",
        )
        s.db.attempts[extra.id] = extra
    elif bad == "provider":
        s.db.attempts[a.id] = replace(a, provider_code="other_gateway")
    else:
        s.db.attempts[a.id] = replace(a, amount=Decimal("1.00"))
    with pytest.raises(RefundDataError):
        await process(s, r)
    assert not s.gateway.calls and not s.db.refund_attempts and s.db.refunds[r.id] == r


async def test_failure_to_persist_verified_event_rolls_back_truth_and_event():
    s, r = await prepare()
    out = await process(s, r)
    s.unit.fail = "history"
    with pytest.raises(RuntimeError):
        await event(s, out.attempt)
    assert s.db.refunds[r.id].status == RefundStatus.PROCESSING
    assert (
        not s.db.refund_events and s.db.refund_attempts[out.attempt.id] == out.attempt
    )
    s.unit.fail = None
    await event(s, out.attempt)
    assert s.db.refunds[r.id].status == RefundStatus.REFUNDED


async def test_webhook_during_provider_response_uses_recoverable_event():
    s, r = await prepare()

    async def early_event():
        body, headers = signed_event(
            None, reference="refund_" + str(s.gateway.calls[-1].attempt_id)
        )
        with pytest.raises(RefundEventPendingError):
            await s.refund_service.webhook("test_gateway", body, headers)

    s.gateway.before_return = early_event
    out = await process(s, r)
    await event(s, out.attempt)
    assert (
        s.db.refunds[r.id].status == RefundStatus.REFUNDED
        and len(s.db.refund_events) == 1
    )


async def test_zero_cash_confirmed_without_gateway():
    s, r = await prepare(method=PaymentMethodType.CASH, total=Decimal("0.00"))
    assert (
        await s.refund_service.confirm_cash(s.admin, s.branch, r.id)
    ).status == RefundStatus.REFUNDED
    assert not s.gateway.calls


async def test_list_pagination_and_filters():
    s, r = await prepare()
    assert await s.refund_service.list_branch(
        s.admin, s.branch, RefundStatus.PENDING, PaymentMethodType.ONLINE
    ) == [r]
    assert (
        await s.refund_service.list_branch(s.admin, s.branch, RefundStatus.FAILED) == []
    )
    assert await s.refund_service.list_branch(s.admin, s.branch, offset=1) == []


async def test_same_cash_operation_two_tasks():
    s, r = await prepare(method=PaymentMethodType.CASH)
    results = await asyncio.gather(
        *(s.refund_service.confirm_cash(s.admin, s.branch, r.id) for _ in range(3))
    )
    assert (
        len({x.refunded_at for x in results}) == 1 and len(s.db.refund_histories) == 2
    )
