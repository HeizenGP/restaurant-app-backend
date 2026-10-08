"""Actual SQL services + test-only signed payment adapter, never a real charge."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.modules.cancellations.domain.models import RequestStatus
from app.modules.cancellations.presentation.dependencies import get_cancellation_service
from app.modules.fulfillment.domain.models import DecisionStatus
from app.modules.orders.domain.models import OrderMode
from app.modules.payments.presentation.refund_dependencies import (
    get_refund_gateway,
    get_refund_service,
)
from app.modules.reviews.presentation.router import get_review_service
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.phase12_support import (
    checkout,
    fresh_database,
    owner,
    pay,
    seed,
    services,
    staff,
)

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


@pytest.mark.parametrize("mode", list(OrderMode))
def test_customer_cart_payment_kitchen_completion_review_and_durable_history(
    request, mode
):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            ids = await seed(factory)
            async with factory() as session:
                order = await checkout(session, ids, mode)
                assert order.total == order.subtotal == 40
                assert order.payment_status == "PENDING"
                await pay(session, ids, order)
                s = services(session)
                if mode == OrderMode.PICKUP:
                    current = await s["orders"].get(owner(ids), order.id)
                    assert current.status == "SCHEDULED"
                    await session.rollback()
                    base = current.pickup_details.calculated_kitchen_release_at
                    ticks = 0

                    def advanced_clock():
                        nonlocal ticks
                        ticks += 1
                        return base + timedelta(minutes=1, seconds=ticks)

                    s["fulfillment"].clock = advanced_clock
                    s["kitchen"]._clock = advanced_clock
                    await s["fulfillment"].release_pickup(
                        staff(ids), ids["branch"], order.id
                    )
                await s["kitchen"].start_preparation(
                    staff(ids, "cook"), ids["branch"], order.id
                )
                await s["kitchen"].mark_ready(
                    staff(ids, "cook"), ids["branch"], order.id
                )
                if mode == OrderMode.LOCAL:
                    await s["orders"].complete_local(
                        staff(ids), ids["branch"], order.id
                    )
                    final = "SERVED"
                elif mode == OrderMode.PICKUP:
                    await s["fulfillment"].complete_pickup(
                        staff(ids),
                        ids["branch"],
                        order.id,
                        "TEST Customer A",
                        "+519000001201",
                    )
                    final = "PICKED_UP"
                else:
                    await s["fulfillment"].assign_delivery(
                        staff(ids), ids["branch"], order.id, ids["admin"]
                    )
                    await s["fulfillment"].dispatch_delivery(
                        staff(ids), ids["branch"], order.id
                    )
                    await s["fulfillment"].complete_delivery(
                        staff(ids), ids["branch"], order.id
                    )
                    final = "DELIVERED"
                review = await get_review_service(session).create(
                    owner(ids), order.id, 5, "TEST completed flow"
                )
                assert review.order_id == order.id
            # A NEW session observes committed data, no identity map shortcut.
            async with factory() as session:
                result = await services(session)["orders"].get(owner(ids), order.id)
                assert result.status == final and result.payment_status == "PAID"
                states = [h.to_status for h in result.history]
                expected = (
                    [
                        "PENDING_CASH_CONFIRMATION",
                        "WAITING",
                        "PREPARING",
                        "READY",
                        "SERVED",
                    ]
                    if mode == OrderMode.LOCAL
                    else [
                        "PENDING_PAYMENT",
                        "SCHEDULED",
                        "WAITING",
                        "PREPARING",
                        "READY_FOR_PICKUP",
                        "PICKED_UP",
                    ]
                    if mode == OrderMode.PICKUP
                    else [
                        "PENDING_PAYMENT",
                        "WAITING",
                        "PREPARING",
                        "READY",
                        "OUT_FOR_DELIVERY",
                        "DELIVERED",
                    ]
                )
                assert states == expected
                assert all(h.created_at.tzinfo for h in result.history)
                assert (
                    await session.scalar(
                        text(
                            "SELECT amount FROM payments "
                            "WHERE order_id=:id AND status='PAID'"
                        ),
                        {"id": order.id},
                    )
                    == result.total
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM customer_notifications "
                            "WHERE order_id=:id"
                        ),
                        {"id": order.id},
                    )
                    >= 3
                )
                assert await session.scalar(
                    text(
                        "SELECT count(*) FROM realtime_order_events WHERE order_id=:id"
                    ),
                    {"id": order.id},
                ) >= len(expected)
                if mode != OrderMode.PICKUP:
                    assert (
                        await session.scalar(
                            text(
                                "SELECT count(*) FROM audit_logs "
                                "WHERE branch_id=:branch AND actor_user_id=:admin"
                            ),
                            ids,
                        )
                        >= 1
                    )

    asyncio.run(scenario())


@pytest.mark.parametrize("late", [False, True])
def test_cancellation_paid_refund_obligation_and_late_payment_never_reactivates(
    request, late
):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            ids = await seed(factory)
            async with factory() as session:
                order = await checkout(
                    session, ids, OrderMode.DELIVERY if late else OrderMode.LOCAL
                )
                s = services(session)
                if late:
                    initiation = await s["payments"].initiate_online(
                        owner(ids), order.id, "TEST-late"
                    )
                else:
                    await pay(session, ids, order)
                cancellations = get_cancellation_service(session)
                requested = await cancellations.create_request(
                    owner(ids), order.id, "TEST customer cancellation"
                )
                await cancellations.review(
                    staff(ids),
                    ids["branch"],
                    requested.request.id,
                    RequestStatus.APPROVED,
                )
                if late:
                    from tests.modules.payments.fakes import signed_event

                    body, headers = signed_event(
                        initiation.attempt,
                        amount=str(order.total),
                        event="TEST-late-success",
                        occurred_at=utc_now(),
                    )
                    await s["payments"].webhook(
                        s["payments"].gateway.provider_code, body, headers
                    )
                refund = await get_refund_service(
                    session, get_refund_gateway()
                ).get_owned(owner(ids), order.id)
                assert refund.amount == order.total and refund.status == "PENDING"
                if not late:
                    returned = await get_refund_service(
                        session, get_refund_gateway()
                    ).confirm_cash(staff(ids), ids["branch"], refund.id)
                    assert returned.status == "REFUNDED"
            async with factory() as session:
                result = await services(session)["orders"].get(owner(ids), order.id)
                assert result.status == "CANCELLED" and result.payment_status == "PAID"
                assert result.history[-1].to_status == "CANCELLED"
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM refunds "
                            "WHERE order_id=:id AND amount=:total"
                        ),
                        {"id": order.id, "total": order.total},
                    )
                    == 1
                )

    asyncio.run(scenario())


def test_delivery_delay_notification_and_admin_evaluation_not_automatic_compensation(
    request,
):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            ids = await seed(factory)
            async with factory() as session:
                order = await checkout(session, ids, OrderMode.DELIVERY)
                await pay(session, ids, order)
                fulfillment = services(session)["fulfillment"]
                fulfillment.clock = lambda: (
                    order.delivery_details.estimated_delivery_at + timedelta(minutes=16)
                )
                found = await fulfillment.detect_delivery_delays(
                    staff(ids), ids["branch"]
                )
                assert found.new_incidents == 1
                incidents = await fulfillment.list_delays(staff(ids), ids["branch"])
                assert incidents[0].decision_status == DecisionStatus.OPEN
                await session.rollback()
                await fulfillment.decide_delay(
                    staff(ids),
                    ids["branch"],
                    incidents[0].id,
                    DecisionStatus.REJECTED,
                    note="TEST evidence reviewed",
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM customer_notifications "
                            "WHERE order_id=:id AND kind='DELIVERY_DELAYED'"
                        ),
                        {"id": order.id},
                    )
                    == 1
                )
                assert await session.scalar(text("SELECT count(*) FROM refunds")) == 0

    asyncio.run(scenario())
