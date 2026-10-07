import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import OrderStatus
from app.modules.payments.application.errors import (
    PaymentConflictError,
    PaymentEventPendingError,
    PaymentNotFoundError,
    PaymentProviderUnavailableError,
)
from app.modules.payments.application.services import PaymentService
from app.modules.payments.domain.models import AttemptStatus, EventStatus, PaymentStatus
from tests.modules.payments.fakes import (
    NOW,
    MemoryOrders,
    MemoryPaymentRepository,
    cash_order,
    change_order,
    initiated,
    send_event,
    signed_event,
)

pytestmark = pytest.mark.anyio


async def test_online_cash_order_rejected_without_provider_call(setup):
    cash_order(setup)
    with pytest.raises(PaymentConflictError):
        await initiated(setup)
    assert not setup.db.payments and not setup.gateway.calls


async def test_cancelled_online_rejects_new_initiation(setup):
    change_order(setup, status=OrderStatus.CANCELLED)
    with pytest.raises(PaymentConflictError):
        await initiated(setup)
    assert not setup.db.payments


async def test_foreign_payment_hidden_even_after_it_exists(setup):
    await initiated(setup)
    with pytest.raises(PaymentNotFoundError):
        await setup.service.get(setup.foreign, setup.order.id)


async def test_distinct_order_gets_distinct_logical_payment_and_attempt(setup):
    first = await initiated(setup)
    other = replace(setup.order, id=uuid4())
    setup.db.orders[other.id] = other
    second = await setup.service.initiate_online(setup.customer, other.id, "key-1")
    assert first.payment.payment.id != second.payment.payment.id
    assert first.attempt.id != second.attempt.id and len(setup.db.payments) == 2


async def test_cash_concurrent_confirmation_has_single_paid_history(setup):
    cash_order(setup)
    repos = [MemoryPaymentRepository(setup.db) for _ in range(2)]
    services = [
        PaymentService(r, MemoryOrders(r), setup.authz, setup.gateway, lambda: NOW)
        for r in repos
    ]
    result = await asyncio.gather(
        *(
            s.confirm_cash(setup.admin, setup.order.branch_id, setup.order.id)
            for s in services
        )
    )
    assert result[0].payment.id == result[1].payment.id
    assert len(setup.db.histories) == 2 and not setup.db.order_histories


async def test_concurrent_success_events_activate_exactly_once(setup):
    result = await initiated(setup)
    repos = [MemoryPaymentRepository(setup.db) for _ in range(2)]
    services = [
        PaymentService(r, MemoryOrders(r), setup.authz, setup.gateway, lambda: NOW)
        for r in repos
    ]
    body, headers = signed_event(result.attempt)
    await asyncio.gather(
        *(s.webhook(setup.gateway.provider_code, body, headers) for s in services)
    )
    assert len(setup.db.events) == 1 and len(setup.db.order_histories) == 1
    assert sum(h.to_status == PaymentStatus.PAID for h in setup.db.histories) == 1


async def test_late_success_with_another_active_attempt_flags_reconciliation(setup):
    old = await initiated(setup)
    await send_event(setup, old.attempt, result="FAILED")
    current = await initiated(setup, "new")
    await send_event(setup, old.attempt, event="old_capture")
    p = next(iter(setup.db.payments.values()))
    assert p.status == PaymentStatus.PAID and p.reconciliation_required
    assert setup.db.attempts[current.attempt.id].status == AttemptStatus.PROCESSING
    assert (
        list(setup.db.events.values())[-1].reason_code
        == "OUTSTANDING_ATTEMPT_RECONCILIATION_REQUIRED"
    )


async def test_provider_response_cannot_erase_a_webhook_confirmation(setup):
    setup.gateway.timeout = True
    with pytest.raises(PaymentProviderUnavailableError):
        await initiated(setup)
    created = next(iter(setup.db.attempts.values()))
    setup.gateway.timeout = False

    async def confirm_before_response():
        # Simulate an already recovered reference (trusted provider recovery).
        a = replace(created, provider_reference="ref_" + str(created.id))
        setup.db.attempts[a.id] = a
        await send_event(setup, a)

    setup.gateway.before_return = confirm_before_response
    result = await initiated(setup)
    assert result.payment.payment.status == PaymentStatus.PAID
    assert (
        result.attempt.status == AttemptStatus.SUCCEEDED
        and result.client_action is None
    )
    assert len(setup.db.order_histories) == 1


async def test_unknown_reference_is_committed_but_requests_delivery_retry(setup):
    class Ref:
        provider_reference = "not-yet-known"

    body, headers = signed_event(Ref())
    for _ in range(2):
        with pytest.raises(PaymentEventPendingError):
            await setup.service.webhook(setup.gateway.provider_code, body, headers)
    assert len(setup.db.events) == 1 and setup.repo.commits == 2
    assert next(iter(setup.db.events.values())).reason_code == "UNKNOWN_REFERENCE"
    assert not setup.db.payments


async def test_audit_rejected_amount_cannot_be_corrected_under_same_event_id(setup):
    result = await initiated(setup)
    await send_event(setup, result.attempt, amount="1.00")
    with pytest.raises(PaymentConflictError):
        await send_event(setup, result.attempt, amount="32.50")
    assert (
        next(iter(setup.db.events.values())).processing_status == EventStatus.REJECTED
    )
    assert next(iter(setup.db.payments.values())).status == PaymentStatus.PROCESSING
