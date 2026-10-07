"""Deterministic independent memory transactions, not PostgreSQL race evidence."""

import asyncio
from dataclasses import replace

import pytest

from app.modules.cancellations.application.errors import CancellationConflictError
from app.modules.cancellations.application.services import CancellationService
from app.modules.cancellations.domain.models import ReasonCode, RequestStatus
from app.modules.orders.domain.models import OrderMode, OrderRuleError, OrderStatus
from app.modules.orders.domain.transitions import validate_transition
from tests.modules.cancellations.fakes import (
    Audit,
    Cleanup,
    Orders,
    Registration,
    Requests,
    Unit,
    cancellation_setup,
)
from tests.modules.fulfillment.test_domain import assignment
from tests.modules.payments.fakes import NOW, signed_event

pytestmark = pytest.mark.anyio


def independent_service(s):
    unit = Unit(s.db)
    return CancellationService(
        Requests(unit),
        Orders(unit),
        s.authz,
        Registration(unit),
        Cleanup(unit),
        Audit(unit),
        clock=lambda: NOW,
    )


async def test_direct_vs_approve_serializes_to_one_historical_cancellation():
    s = cancellation_setup()
    r = (await s.service.create_request(s.customer, s.order.id, "Plans")).request
    other = independent_service(s)
    await asyncio.gather(
        s.service.cancel_order(s.admin, s.branch, s.order.id, ReasonCode.OUT_OF_STOCK),
        other.review(s.admin, s.branch, r.id, RequestStatus.APPROVED),
        return_exceptions=True,
    )
    assert len(s.db.cancellations) == 1 and len(s.db.refunds) == 1
    assert (
        s.db.requests[r.id].status == RequestStatus.APPROVED
        and len(s.db.order_histories) == 1
    )


async def test_approve_vs_reject_one_decision_only():
    s = cancellation_setup()
    r = (await s.service.create_request(s.customer, s.order.id, "Plans")).request
    other = independent_service(s)
    results = await asyncio.gather(
        s.service.review(s.admin, s.branch, r.id, RequestStatus.APPROVED),
        other.review(s.admin, s.branch, r.id, RequestStatus.REJECTED),
        return_exceptions=True,
    )
    assert sum(isinstance(x, CancellationConflictError) for x in results) == 1
    assert s.db.requests[r.id].status == RequestStatus.APPROVED
    assert len(s.db.refunds) == 1 and len(s.db.order_histories) == 1


@pytest.mark.parametrize(
    "target,mode,initial",
    [
        (OrderStatus.PREPARING, OrderMode.LOCAL, OrderStatus.WAITING),
        (OrderStatus.OUT_FOR_DELIVERY, OrderMode.DELIVERY, OrderStatus.READY),
    ],
)
@pytest.mark.parametrize("cancel_first", [True, False])
async def test_cancel_vs_normal_fulfillment_never_reactivates(
    target, mode, initial, cancel_first
):
    s = cancellation_setup()
    s.db.orders[s.order.id] = replace(s.order, status=initial, mode=mode)
    unit = Unit(s.db)

    async def normal_transition():
        await unit.begin()
        try:
            old = s.db.orders[s.order.id]
            validate_transition(old, target)
            s.db.orders[old.id] = replace(old, status=target)
            s.db.order_histories.append((old.id, old.status, target))
            await unit.commit()
        except Exception:
            await unit.rollback()
            raise

    cancel = s.service.cancel_order(
        s.admin, s.branch, s.order.id, ReasonCode.OUT_OF_STOCK
    )
    tasks = (
        [cancel, normal_transition()] if cancel_first else [normal_transition(), cancel]
    )
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    assert len(s.db.refunds) == 1
    if cancel_first:
        assert any(isinstance(x, OrderRuleError) for x in results)


async def test_delivery_cancellation_closes_not_deletes_assignment():
    s = cancellation_setup()
    s.db.orders[s.order.id] = replace(
        s.order, mode=OrderMode.DELIVERY, status=OrderStatus.OUT_FOR_DELIVERY
    )
    a = replace(assignment(), order_id=s.order.id)
    s.db.assignments[a.id] = a
    await s.service.cancel_order(s.admin, s.branch, s.order.id, ReasonCode.OUT_OF_STOCK)
    closed = s.db.assignments[a.id]
    assert (
        closed.unassigned_at == NOW and closed.unassigned_by_user_id == s.admin.user_id
    )
    assert (
        closed.reason == "Order cancelled"
        and closed.assigned_user_id == a.assigned_user_id
    )
    assert len(s.db.assignments) == 1


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_payment_success_vs_cancellation_final_invariant(cancel_first):
    s = cancellation_setup(paid=False)
    started = await s.payment_service.initiate_online(
        s.customer, s.order.id, "key-original"
    )
    body, headers = signed_event(started.attempt)
    # Give cancellation its own independent transaction adapter.
    cancellation = independent_service(s).cancel_order(
        s.admin, s.branch, s.order.id, ReasonCode.OUT_OF_STOCK
    )
    payment = s.payment_service.webhook("test_gateway", body, headers)
    await asyncio.gather(
        *([cancellation, payment] if cancel_first else [payment, cancellation])
    )
    assert s.db.orders[s.order.id].status == OrderStatus.CANCELLED
    assert len(s.db.refunds) == 1 and len(s.db.refund_histories) == 1
