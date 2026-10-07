import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
)
from app.modules.orders.domain.models import (
    PaymentStatus as OrdersPaid,
)
from app.modules.payments.application.errors import (
    PaymentCashPermissionDeniedError,
    PaymentConflictError,
    PaymentDataError,
    PaymentEventPendingError,
    PaymentNotFoundError,
    PaymentProviderUnavailableError,
    PaymentWebhookAuthenticationError,
)
from app.modules.payments.application.services import PaymentService
from app.modules.payments.domain.models import (
    AttemptStatus,
    EventStatus,
    HistorySource,
    PaymentStatus,
)
from app.modules.payments.infrastructure.gateway import UnconfiguredOnlinePaymentGateway
from tests.modules.payments.fakes import (
    NOW,
    MemoryOrders,
    MemoryPaymentRepository,
    cash_order,
    change_order,
    initiated,
    send_event,
)

pytestmark = pytest.mark.anyio


async def test_get_is_read_only_not_lazy_creation(setup):
    with pytest.raises(PaymentNotFoundError):
        await setup.service.get(setup.customer, setup.order.id)
    assert not setup.db.payments and setup.repo.commits == 0


@pytest.mark.parametrize("who", ["guest", "foreign"])
async def test_foreign_customer_does_not_create_payment(setup, who):
    with pytest.raises(PaymentNotFoundError):
        await setup.service.initiate_online(getattr(setup, who), setup.order.id, "key")
    assert not setup.db.payments and not setup.gateway.calls


async def test_guest_owns_online_order(setup):
    change_order(setup, customer_id=setup.guest.customer_id)
    result = await setup.service.initiate_online(setup.guest, setup.order.id, "guest")
    assert result.payment.payment.status == PaymentStatus.PROCESSING
    assert setup.db.histories[-1].changed_by_user_id is None


async def test_online_initiation_reserves_historical_amount_and_does_not_activate(
    setup,
):
    result = await initiated(setup)
    assert result.payment.payment.amount == setup.order.total
    assert result.attempt.status == AttemptStatus.PROCESSING
    assert result.client_action
    assert setup.db.orders[setup.order.id] == setup.order
    assert not setup.db.order_histories
    req = setup.gateway.calls[0]
    assert req.amount == Decimal("32.50") and req.currency_code == "PEN"
    assert req.provider_idempotency_key == "payment-attempt:" + str(result.attempt.id)
    assert setup.repo.commits == 2
    assert [h.to_status for h in setup.db.histories] == [
        PaymentStatus.PENDING,
        PaymentStatus.PROCESSING,
    ]


async def test_same_key_replays_attempt_and_client_action(setup):
    first = await initiated(setup)
    second = await initiated(setup)
    assert (
        second == first
        and len(setup.gateway.calls) == 1
        and len(setup.db.attempts) == 1
    )


async def test_other_key_cannot_start_parallel_attempt(setup):
    await initiated(setup)
    with pytest.raises(PaymentConflictError) as err:
        await initiated(setup, "new")
    assert err.value.code == "PAYMENT_IDEMPOTENCY_CONFLICT"
    assert len(setup.db.attempts) == 1 and len(setup.gateway.calls) == 1


async def test_unconfigured_provider_fails_closed_before_new_writes(setup):
    setup.service.gateway = UnconfiguredOnlinePaymentGateway()
    with pytest.raises(PaymentProviderUnavailableError):
        await initiated(setup)
    assert not setup.db.payments and not setup.db.attempts and not setup.db.histories


async def test_unconfigured_webhook_touches_no_repository(setup):
    setup.service.gateway = UnconfiguredOnlinePaymentGateway()
    with pytest.raises(PaymentProviderUnavailableError):
        await setup.service.webhook("future", b'{"status":"PAID"}', {})
    assert not setup.db.events and not setup.db.payments


async def test_unavailable_provider_does_not_hide_ownership(setup):
    setup.service.gateway = UnconfiguredOnlinePaymentGateway()
    with pytest.raises(PaymentNotFoundError):
        await setup.service.initiate_online(setup.foreign, setup.order.id, "key")


async def test_timeout_keeps_recoverable_created_attempt(setup):
    setup.gateway.timeout = True
    with pytest.raises(PaymentProviderUnavailableError):
        await initiated(setup)
    a = next(iter(setup.db.attempts.values()))
    assert a.status == AttemptStatus.CREATED
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PROCESSING
    assert not setup.db.order_histories
    setup.gateway.timeout = False
    result = await initiated(setup)
    assert result.attempt.id == a.id
    assert len(setup.db.attempts) == 1 and len(setup.gateway.operations) == 1
    assert len({r.provider_idempotency_key for r in setup.gateway.calls}) == 1


async def test_different_key_during_ambiguous_timeout_is_rejected(setup):
    setup.gateway.timeout = True
    with pytest.raises(PaymentProviderUnavailableError):
        await initiated(setup)
    with pytest.raises(PaymentConflictError):
        await initiated(setup, "other")


async def test_real_decline_is_not_paid_and_new_key_may_retry(setup):
    setup.gateway.decline = True
    first = await initiated(setup)
    assert first.attempt.status == AttemptStatus.FAILED
    assert first.attempt.failure_code == "PAYMENT_DECLINED"
    assert first.payment.payment.status == PaymentStatus.FAILED
    assert (await initiated(setup)).attempt.id == first.attempt.id
    setup.gateway.decline = False
    second = await initiated(setup, "new")
    assert second.payment.payment.id == first.payment.payment.id
    assert second.attempt.id != first.attempt.id
    assert len(setup.db.payments) == 1 and len(setup.db.attempts) == 2
    assert setup.db.orders[setup.order.id].status == OrderStatus.PENDING_PAYMENT


@pytest.mark.parametrize(
    "state",
    [
        OrderStatus.PENDING_CASH_CONFIRMATION,
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.SERVED,
    ],
)
async def test_cash_actual_receipt_preserves_operational_lifecycle(setup, state):
    order = cash_order(setup, status=state)
    first = await setup.service.confirm_cash(setup.admin, order.branch_id, order.id)
    second = await setup.service.confirm_cash(setup.admin, order.branch_id, order.id)
    assert first == second
    assert first.payment.status == PaymentStatus.PAID and first.payment.paid_at == NOW
    current = setup.db.orders[order.id]
    assert current.status == order.status and current.confirmed_at == order.confirmed_at
    assert current.payment_status == OrdersPaid.PAID
    assert not setup.db.attempts and not setup.db.order_histories
    assert len(setup.db.histories) == 2
    assert setup.db.histories[-1].source == HistorySource.STAFF
    assert setup.db.histories[-1].changed_by_user_id == setup.admin.user_id


@pytest.mark.parametrize("who", ["guest", "customer", "foreign", "kitchen"])
async def test_cash_permission_denied(setup, who):
    cash_order(setup)
    with pytest.raises(PaymentCashPermissionDeniedError):
        await setup.service.confirm_cash(
            getattr(setup, who), setup.order.branch_id, setup.order.id
        )
    assert not setup.db.payments


async def test_wrong_branch_hidden_with_authorized_branch(setup):
    cash_order(setup)
    branch = uuid4()
    setup.authz.grants.add((setup.admin.user_id, branch, "PAYMENT_CASH_MANAGE"))
    with pytest.raises(PaymentNotFoundError):
        await setup.service.confirm_cash(setup.admin, branch, setup.order.id)


async def test_cash_rejects_online_and_cancelled(setup):
    with pytest.raises(PaymentConflictError):
        await setup.service.confirm_cash(
            setup.admin, setup.order.branch_id, setup.order.id
        )
    cash_order(setup, status=OrderStatus.CANCELLED)
    with pytest.raises(PaymentConflictError):
        await setup.service.confirm_cash(
            setup.admin, setup.order.branch_id, setup.order.id
        )
    assert not setup.db.payments


@pytest.mark.parametrize("failure", ["fail_order", "fail_commit"])
async def test_cash_failure_rolls_back_payment_order_history(setup, failure):
    cash_order(setup)
    setattr(setup.repo, failure, True)
    with pytest.raises(RuntimeError):
        await setup.service.confirm_cash(
            setup.admin, setup.order.branch_id, setup.order.id
        )
    assert not setup.db.payments and not setup.db.histories
    assert setup.db.orders[setup.order.id].payment_status == OrdersPaid.PENDING


@pytest.mark.parametrize(
    "mode,offset,target",
    [
        (OrderMode.LOCAL, None, OrderStatus.WAITING),
        (OrderMode.DELIVERY, None, OrderStatus.WAITING),
        (OrderMode.PICKUP, 10, OrderStatus.SCHEDULED),
        (OrderMode.PICKUP, 0, OrderStatus.WAITING),
        (OrderMode.PICKUP, -10, OrderStatus.WAITING),
    ],
)
async def test_verified_online_success_activates_via_orders(
    setup, mode, offset, target
):
    change_order(
        setup,
        mode=mode,
        calculated_kitchen_release_at=NOW + timedelta(minutes=offset)
        if offset is not None
        else None,
    )
    result = await initiated(setup)
    await send_event(setup, result.attempt)
    p = next(iter(setup.db.payments.values()))
    a = setup.db.attempts[result.attempt.id]
    o = setup.db.orders[setup.order.id]
    assert p.status == PaymentStatus.PAID and p.paid_at == NOW
    assert a.status == AttemptStatus.SUCCEEDED and a.client_action is None
    assert (
        o.status == target
        and o.confirmed_at == NOW
        and o.payment_status == OrdersPaid.PAID
    )
    assert len(setup.db.order_histories) == 1 and setup.db.order_histories[0][1:3] == (
        OrderStatus.PENDING_PAYMENT,
        target,
    )
    h = setup.db.histories[-1]
    assert (
        h.source == HistorySource.PROVIDER
        and h.changed_by_user_id is None
        and h.provider_event_id == "evt_1"
    )


async def test_duplicate_event_is_idempotent_but_still_authenticated(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt)
    await send_event(setup, result.attempt)
    assert len(setup.db.events) == 1 and len(setup.db.order_histories) == 1
    assert len(setup.db.histories) == 3 and setup.gateway.verify_calls == 2


async def test_same_success_different_ids_does_not_add_paid_history(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt)
    await send_event(setup, result.attempt, event="evt_2")
    assert len(setup.db.events) == 2 and len(setup.db.histories) == 3
    assert list(setup.db.events.values())[-1].processing_status == EventStatus.IGNORED


async def test_event_id_payload_collision_is_rejected(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt)
    with pytest.raises(PaymentConflictError):
        await send_event(setup, result.attempt, amount="999.00")
    assert next(iter(setup.db.events.values())).reported_amount == Decimal("32.50")
    assert len(setup.db.histories) == 3


async def test_unverified_customer_paid_json_does_not_touch_db(setup):
    with pytest.raises(PaymentWebhookAuthenticationError):
        await setup.service.webhook("test_gateway", b'{"status":"PAID"}', {})
    assert not setup.db.events and not setup.db.trace


@pytest.mark.parametrize(
    "amount,currency,reason",
    [
        ("32.49", "PEN", "AMOUNT_MISMATCH"),
        ("32.51", "PEN", "AMOUNT_MISMATCH"),
        ("32.50", "USD", "CURRENCY_MISMATCH"),
    ],
)
async def test_mismatched_verified_money_is_audited_not_paid(
    setup, amount, currency, reason
):
    result = await initiated(setup)
    await send_event(setup, result.attempt, amount=amount, currency=currency)
    event = next(iter(setup.db.events.values()))
    assert (
        event.processing_status == EventStatus.REJECTED and event.reason_code == reason
    )
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PROCESSING
    assert setup.db.orders[setup.order.id].status == OrderStatus.PENDING_PAYMENT
    assert not setup.db.order_histories


async def test_unknown_reference_preserves_evidence_without_phantom_payment(setup):
    class Ref:
        provider_reference = "unknown"

    with pytest.raises(PaymentEventPendingError):
        await send_event(setup, Ref())
    event = next(iter(setup.db.events.values()))
    assert (
        event.reason_code == "UNKNOWN_REFERENCE"
        and event.processing_status == EventStatus.REJECTED
    )
    assert not setup.db.payments and not setup.db.attempts


async def test_early_event_can_reconcile_when_reference_is_persisted(setup):
    async def early():
        class Ref:
            provider_reference = next(
                iter(setup.gateway.operations.values())
            ).provider_reference

        with pytest.raises(PaymentEventPendingError):
            await send_event(setup, Ref())

    setup.gateway.before_return = early
    result = await initiated(setup)
    assert next(iter(setup.db.events.values())).reason_code == "UNKNOWN_REFERENCE"
    setup.gateway.before_return = None
    await send_event(setup, result.attempt)
    assert (
        next(iter(setup.db.events.values())).processing_status == EventStatus.PROCESSED
    )
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PAID


async def test_failure_never_activates_order_and_can_retry(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt, result="FAILED")
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.FAILED
    assert not setup.db.order_histories
    again = await initiated(setup, "second")
    assert (
        again.attempt.id != result.attempt.id
        and again.payment.payment.status == PaymentStatus.PROCESSING
    )


async def test_old_failure_does_not_fail_new_attempt(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt, result="FAILED")
    newer = await initiated(setup, "second")
    await send_event(setup, result.attempt, event="old_failure", result="FAILED")
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PROCESSING
    assert setup.db.attempts[newer.attempt.id].status == AttemptStatus.PROCESSING


async def test_paid_cannot_be_downgraded_by_late_failure(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt)
    await send_event(setup, result.attempt, event="failure", result="FAILED")
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PAID
    assert setup.db.attempts[result.attempt.id].status == AttemptStatus.SUCCEEDED
    assert len(setup.db.histories) == 3 and len(setup.db.order_histories) == 1


async def test_late_success_after_decline_uses_legal_recovery_graph(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt, result="FAILED")
    await send_event(setup, result.attempt, event="late")
    assert [h.to_status for h in setup.db.histories] == [
        PaymentStatus.PENDING,
        PaymentStatus.PROCESSING,
        PaymentStatus.FAILED,
        PaymentStatus.PROCESSING,
        PaymentStatus.PAID,
    ]
    assert setup.db.orders[setup.order.id].status == OrderStatus.WAITING


async def test_second_distinct_capture_is_audited_not_hidden(setup):
    old = await initiated(setup)
    await send_event(setup, old.attempt, result="FAILED")
    new = await initiated(setup, "new")
    await send_event(setup, new.attempt, event="new_success")
    await send_event(setup, old.attempt, event="old_success")
    p = next(iter(setup.db.payments.values()))
    assert p.status == PaymentStatus.PAID and p.reconciliation_required
    assert all(a.status == AttemptStatus.SUCCEEDED for a in setup.db.attempts.values())
    assert sum(h.to_status == PaymentStatus.PAID for h in setup.db.histories) == 1
    assert len(setup.db.order_histories) == 1
    assert (
        list(setup.db.events.values())[-1].reason_code
        == "ADDITIONAL_CAPTURE_RECONCILIATION_REQUIRED"
    )


async def test_cancelled_paid_truth_does_not_resurrect_order(setup):
    result = await initiated(setup)
    change_order(setup, status=OrderStatus.CANCELLED)
    await send_event(setup, result.attempt)
    p = next(iter(setup.db.payments.values()))
    o = setup.db.orders[setup.order.id]
    assert p.status == PaymentStatus.PAID and p.reconciliation_required
    assert o.status == OrderStatus.CANCELLED and o.payment_status == OrdersPaid.PAID
    assert o.confirmed_at is None and not setup.db.order_histories
    assert (
        next(iter(setup.db.events.values())).reason_code
        == "PAID_AFTER_CANCELLATION_RECONCILIATION_REQUIRED"
    )


async def test_provider_future_timestamp_cannot_change_pickup_release_decision(setup):
    change_order(
        setup,
        mode=OrderMode.PICKUP,
        calculated_kitchen_release_at=NOW + timedelta(minutes=5),
    )
    result = await initiated(setup)
    await send_event(setup, result.attempt, occurred_at=NOW + timedelta(days=100))
    assert setup.db.orders[setup.order.id].status == OrderStatus.SCHEDULED
    assert next(iter(setup.db.payments.values())).paid_at == NOW


@pytest.mark.parametrize("failure", ["fail_order", "fail_commit"])
async def test_webhook_failure_rolls_back_every_financial_and_order_write(
    setup, failure
):
    result = await initiated(setup)
    setattr(setup.repo, failure, True)
    with pytest.raises(RuntimeError):
        await send_event(setup, result.attempt)
    assert not setup.db.events and not setup.db.order_histories
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PROCESSING
    assert setup.db.attempts[result.attempt.id].status == AttemptStatus.PROCESSING
    assert len(setup.db.histories) == 2
    setattr(setup.repo, failure, False)
    await send_event(setup, result.attempt)
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PAID


async def test_paid_same_key_replays_without_action_new_key_conflicts(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt)
    replay = await initiated(setup)
    assert (
        replay.payment.payment.status == PaymentStatus.PAID
        and replay.client_action is None
    )
    assert len(setup.gateway.calls) == 1
    with pytest.raises(PaymentConflictError):
        await initiated(setup, "new")


async def test_legacy_paid_order_without_ledger_is_not_fabricated(setup):
    cash_order(setup, status=OrderStatus.SERVED)
    change_order(setup, payment_status=OrdersPaid.PAID)
    with pytest.raises(PaymentDataError):
        await setup.service.confirm_cash(
            setup.admin, setup.order.branch_id, setup.order.id
        )
    assert not setup.db.payments


async def test_backend_amount_inconsistency_fails_safely(setup):
    await initiated(setup)
    change_order(setup, total=Decimal("100.00"))
    with pytest.raises(PaymentDataError):
        await initiated(setup)
    assert len(setup.gateway.calls) == 1


async def test_webhook_lock_order_is_order_payment_attempt(setup):
    result = await initiated(setup)
    setup.db.trace.clear()
    await send_event(setup, result.attempt)
    assert setup.db.trace == ["order", "payment", "attempt"]


async def test_concurrent_same_key_reservations_use_one_provider_operation(setup):
    repositories = [MemoryPaymentRepository(setup.db) for _ in range(2)]
    services = [
        PaymentService(r, MemoryOrders(r), setup.authz, setup.gateway, lambda: NOW)
        for r in repositories
    ]
    result = await asyncio.gather(
        *(s.initiate_online(setup.customer, setup.order.id, "same") for s in services)
    )
    assert result[0].attempt.id == result[1].attempt.id
    assert len(setup.db.attempts) == 1 and len(setup.gateway.operations) == 1
