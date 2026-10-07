import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.cancellations.application.errors import (
    CancellationConflictError,
    CancellationNotFoundError,
    CancellationPermissionDeniedError,
)
from app.modules.cancellations.domain.models import ReasonCode, RequestStatus
from app.modules.orders.domain.cancellations import CANCELLABLE_STATUSES
from app.modules.orders.domain.models import OrderStatus, PaymentMethodType
from app.modules.orders.domain.models import PaymentStatus as OrderPaid
from app.modules.payments.application.refund_errors import RefundDataError
from app.modules.payments.domain.models import PaymentStatus
from app.modules.payments.domain.refunds import RefundStatus
from tests.modules.cancellations.fakes import cancellation_setup
from tests.modules.payments.fakes import signed_event

pytestmark = pytest.mark.anyio


async def cancel(s):
    return await s.service.cancel_order(
        s.admin, s.branch, s.order.id, ReasonCode.OUT_OF_STOCK
    )


async def test_customer_request_does_not_cancel_or_create_refund(setup):
    s = setup
    created = await s.service.create_request(
        s.customer, s.order.id, "  Changed plans  "
    )
    again = await s.service.create_request(s.customer, s.order.id, "Changed plans")
    assert created.created and not again.created and created.request == again.request
    assert s.db.orders[s.order.id].status == OrderStatus.WAITING
    assert not s.db.refunds and not s.db.cancellations and not s.db.audits
    with pytest.raises(CancellationConflictError):
        await s.service.create_request(s.customer, s.order.id, "Different reason")


async def test_approve_has_atomic_order_refund_and_audit(setup):
    s = setup
    r = (
        await s.service.create_request(s.customer, s.order.id, "Changed plans")
    ).request
    original = next(iter(s.db.payments.values()))
    out = await s.service.review(
        s.admin, s.branch, r.id, RequestStatus.APPROVED, "Checked"
    )
    assert out.refund.amount == original.amount == s.order.total
    assert out.refund.status == RefundStatus.PENDING
    assert (
        s.db.payments[original.id] == original and original.status == PaymentStatus.PAID
    )
    assert s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    assert s.db.orders[s.order.id].payment_status == OrderPaid.PAID
    assert s.db.requests[r.id].status == RequestStatus.APPROVED
    assert (
        len(s.db.refund_histories) == 1
        and len(s.db.order_histories) == 1
        and len(s.db.audits) == 2
    )
    assert (
        await s.service.review(
            s.admin, s.branch, r.id, RequestStatus.APPROVED, "Checked"
        )
        == out
    )
    assert len(s.db.refunds) == 1 and len(s.db.order_histories) == 1
    with pytest.raises(CancellationConflictError):
        await s.service.review(
            s.admin, s.branch, r.id, RequestStatus.REJECTED, "Checked"
        )


async def test_reject_preserves_order_and_allows_new_request(setup):
    s = setup
    r = (
        await s.service.create_request(s.customer, s.order.id, "Changed plans")
    ).request
    rejected = await s.service.review(
        s.admin, s.branch, r.id, RequestStatus.REJECTED, "Cannot approve"
    )
    assert rejected.status == RequestStatus.REJECTED
    assert not s.db.refunds and not s.db.cancellations and not s.db.order_histories
    assert s.db.orders[s.order.id] == s.order
    assert (
        await s.service.review(
            s.admin, s.branch, r.id, RequestStatus.REJECTED, "Cannot approve"
        )
        == rejected
    )
    new = await s.service.create_request(s.customer, s.order.id, "Another reason")
    assert new.request.id != r.id and len(s.db.requests) == 2


@pytest.mark.parametrize("status", list(CANCELLABLE_STATUSES))
async def test_admin_cancels_supported_states(status):
    s = cancellation_setup()
    s.db.orders[s.order.id] = replace(s.order, status=status)
    assert (await cancel(s)).refund.status == RefundStatus.PENDING


@pytest.mark.parametrize(
    "status", [OrderStatus.SERVED, OrderStatus.PICKED_UP, OrderStatus.DELIVERED]
)
async def test_terminal_status_never_cancelled(status):
    s = cancellation_setup()
    s.db.orders[s.order.id] = replace(s.order, status=status)
    with pytest.raises(CancellationConflictError):
        await cancel(s)
    assert not s.db.refunds and not s.db.cancellations


async def test_direct_resolves_pending_request_and_exact_retry(setup):
    s = setup
    r = (
        await s.service.create_request(s.customer, s.order.id, "Changed plans")
    ).request
    out = await cancel(s)
    assert s.db.requests[r.id].status == RequestStatus.APPROVED
    assert out.cancellation.cancellation_request_id is None
    assert await cancel(s) == out
    with pytest.raises(CancellationConflictError):
        await s.service.cancel_order(
            s.admin, s.branch, s.order.id, ReasonCode.OTHER, "Changed reason"
        )
    assert len(s.db.cancellations) == 1 and len(s.db.refunds) == 1


@pytest.mark.parametrize(
    "step",
    ["order", "cancellation", "refund", "history", "assignment", "audit", "commit"],
)
async def test_every_failure_rolls_back_all_cross_slice_writes(step):
    s = cancellation_setup()
    r = (await s.service.create_request(s.customer, s.order.id, "Plans")).request
    s.unit.fail = step
    with pytest.raises(RuntimeError):
        await s.service.review(s.admin, s.branch, r.id, RequestStatus.APPROVED)
    assert s.db.orders[s.order.id] == s.order
    assert s.db.requests[r.id].status == RequestStatus.PENDING
    assert (
        not s.db.cancellations
        and not s.db.refunds
        and not s.db.refund_histories
        and not s.db.audits
        and not s.db.order_histories
    )
    assert not s.db.mutex.locked()


@pytest.mark.parametrize("bad", ["missing", "amount", "pending"])
async def test_incoherent_paid_payment_is_safe_failure(bad):
    s = cancellation_setup()
    p = next(iter(s.db.payments.values()))
    if bad == "missing":
        s.db.payments.clear()
    else:
        s.db.payments[p.id] = (
            replace(p, amount=Decimal("1.00"))
            if bad == "amount"
            else replace(p, status=PaymentStatus.PENDING, paid_at=None)
        )
    with pytest.raises(RefundDataError):
        await cancel(s)
    assert s.db.orders[s.order.id] == s.order
    assert not s.db.cancellations and not s.db.refunds


async def test_unpaid_cancel_creates_no_refund():
    s = cancellation_setup(paid=False)
    assert (await cancel(s)).refund is None
    assert not s.db.refunds and not s.db.payments


async def test_zero_paid_cancel_has_explicit_pending_obligation():
    s = cancellation_setup(total=Decimal("0.00"))
    assert (await cancel(s)).refund.amount == Decimal("0.00")


@pytest.mark.parametrize("who", ["customer", "guest", "foreign", "kitchen"])
async def test_non_admin_cannot_cancel(who):
    s = cancellation_setup()
    with pytest.raises(CancellationPermissionDeniedError):
        await s.service.cancel_order(
            getattr(s, who), s.branch, s.order.id, ReasonCode.OUT_OF_STOCK
        )
    assert not s.db.cancellations


async def test_scope_before_id_and_ownership(setup):
    s = setup
    with pytest.raises(CancellationNotFoundError):
        await s.service.create_request(s.foreign, s.order.id, "Plans")
    other = uuid4()
    s.authz.grants.add((s.admin.user_id, other, "CANCELLATION_MANAGE"))
    with pytest.raises(CancellationNotFoundError):
        await s.service.cancel_order(
            s.admin, other, s.order.id, ReasonCode.OUT_OF_STOCK
        )


async def test_guest_owner_can_only_request(setup):
    s = setup
    s.db.orders[s.order.id] = replace(s.order, customer_id=s.guest.customer_id)
    assert (await s.service.create_request(s.guest, s.order.id, "Plans")).created
    assert not s.db.cancellations and not s.db.refunds


async def test_same_request_concurrency_is_idempotent(setup):
    s = setup
    results = await asyncio.gather(
        *(s.service.create_request(s.customer, s.order.id, "Plans") for _ in range(5))
    )
    assert sum(r.created for r in results) == 1 and len(s.db.requests) == 1


@pytest.mark.parametrize("payment_first", [False, True])
async def test_late_real_payment_always_registers_refund(payment_first):
    s = cancellation_setup(paid=False)
    started = await s.payment_service.initiate_online(
        s.customer, s.order.id, "original-payment"
    )
    body, headers = signed_event(started.attempt)
    if payment_first:
        await s.payment_service.webhook("test_gateway", body, headers)
    await cancel(s)
    await s.payment_service.webhook("test_gateway", body, headers)
    assert s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    assert s.db.orders[s.order.id].payment_status == OrderPaid.PAID
    assert len(s.db.refunds) == 1 and len(s.db.refund_histories) == 1
    assert next(iter(s.db.payments.values())).status == PaymentStatus.PAID


async def test_late_payment_refund_failure_rolls_back_capture():
    s = cancellation_setup(paid=False)
    started = await s.payment_service.initiate_online(
        s.customer, s.order.id, "original-payment"
    )
    await cancel(s)
    s.unit.fail = "refund"
    body, headers = signed_event(started.attempt)
    with pytest.raises(RuntimeError):
        await s.payment_service.webhook("test_gateway", body, headers)
    assert s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    assert s.db.orders[s.order.id].payment_status == OrderPaid.PENDING
    assert next(iter(s.db.payments.values())).status == PaymentStatus.PROCESSING
    assert not s.db.refunds and not s.db.events


async def test_cash_paid_cancellation_owns_separate_refund():
    s = cancellation_setup(method=PaymentMethodType.CASH)
    p = next(iter(s.db.payments.values()))
    assert (await cancel(s)).refund.method_type == PaymentMethodType.CASH
    assert s.db.payments[p.id] == p
