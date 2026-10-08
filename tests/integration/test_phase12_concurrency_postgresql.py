"""Distinct backend PIDs and synchronized competing SQL sessions, not mocks."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.modules.cancellations.domain.models import RequestStatus
from app.modules.cancellations.presentation.dependencies import get_cancellation_service
from app.modules.cart.application.dtos import ItemCreate, ItemUpdate
from app.modules.orders.application.dtos import OrderCreate
from app.modules.orders.domain.models import OrderMode, PaymentMethodType
from app.modules.payments.presentation.refund_dependencies import (
    get_refund_gateway,
    get_refund_service,
)
from app.shared.application.exceptions import ApplicationError
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.modules.payments.fakes import signed_event
from tests.phase12_support import (
    checkout,
    fresh_database,
    owner,
    pay,
    seed,
    services,
    staff,
)

pytestmark = pytest.mark.integration


async def race(factory, work):
    barrier = asyncio.Barrier(2)
    pids = set()

    async def competitor(index):
        async with factory() as session:
            pids.add(await session.scalar(text("SELECT pg_backend_pid()")))
            await barrier.wait()
            await session.rollback()
            try:
                return await work(session, index)
            except ApplicationError as error:
                await session.rollback()
                return error

    results = await asyncio.wait_for(asyncio.gather(competitor(0), competitor(1)), 30)
    assert len(pids) == 2
    return results


@pytest.mark.parametrize(
    "case",
    [
        "cart_update",
        "checkout_same_key",
        "checkout_different_key",
        "kitchen",
        "cash",
        "cash_refund",
        "pickup_release",
        "delivery_assignment",
        "cancel_kitchen",
        "cancel_payment",
        "serve_local",
    ],
)
def test_real_two_connection_cross_slice_races(request, case):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            ids = await seed(factory)
            order = item = refund = cancellation = initiation = None
            async with factory() as session:
                s = services(session)
                if case in {
                    "cart_update",
                    "checkout_same_key",
                    "checkout_different_key",
                }:
                    await s["cart"].create_cart(owner(ids), ids["branch"])
                    item = await s["cart"].add_item(
                        owner(ids),
                        ItemCreate(
                            product_id=ids["product"],
                            presentation_id=ids["presentation"],
                            quantity=1,
                        ),
                    )
                else:
                    mode = (
                        OrderMode.PICKUP
                        if case == "pickup_release"
                        else OrderMode.DELIVERY
                        if case in {"delivery_assignment", "cancel_payment"}
                        else OrderMode.LOCAL
                    )
                    order = await checkout(session, ids, mode)
                    if case == "cancel_payment":
                        initiation = await s["payments"].initiate_online(
                            owner(ids), order.id, "TEST-cancel-payment-race"
                        )
                    elif case != "cash":
                        await pay(session, ids, order)
                    if case in {"cash_refund", "cancel_kitchen", "cancel_payment"}:
                        cancellations = get_cancellation_service(session)
                        cancellation = (
                            await cancellations.create_request(
                                owner(ids), order.id, "TEST race cancellation"
                            )
                        ).request
                        if case == "cash_refund":
                            await cancellations.review(
                                staff(ids),
                                ids["branch"],
                                cancellation.id,
                                RequestStatus.APPROVED,
                            )
                            refund = await get_refund_service(
                                session, get_refund_gateway()
                            ).get_owned(owner(ids), order.id)
                            await session.rollback()
                    if case == "serve_local":
                        await s["kitchen"].start_preparation(
                            staff(ids, "cook"), ids["branch"], order.id
                        )
                        await s["kitchen"].mark_ready(
                            staff(ids, "cook"), ids["branch"], order.id
                        )

            async def work(session, index):
                s = services(session)
                if case == "cart_update":
                    return await s["cart"].update_item(
                        owner(ids),
                        item.id,
                        ItemUpdate(
                            provided_fields=frozenset({"quantity"}), quantity=3 + index
                        ),
                    )
                if case.startswith("checkout"):
                    command = OrderCreate(
                        mode=OrderMode.LOCAL,
                        payment_method=PaymentMethodType.CASH,
                        table_qr_token=ids["qr"],
                    )
                    return await s["orders"].create(
                        owner(ids),
                        "TEST-checkout"
                        + (str(index) if case.endswith("different_key") else ""),
                        command,
                    )
                if case == "kitchen" or (case == "cancel_kitchen" and index == 1):
                    return await s["kitchen"].start_preparation(
                        staff(ids, "cook"), ids["branch"], order.id
                    )
                if case == "cash":
                    return await s["payments"].confirm_cash(
                        staff(ids), ids["branch"], order.id
                    )
                if case == "cash_refund":
                    return await get_refund_service(
                        session, get_refund_gateway()
                    ).confirm_cash(staff(ids), ids["branch"], refund.id)
                if case == "pickup_release":
                    s["fulfillment"].clock = lambda: (
                        order.pickup_details.calculated_kitchen_release_at
                        + timedelta(minutes=1)
                    )
                    return await s["fulfillment"].release_pickup(
                        staff(ids), ids["branch"], order.id
                    )
                if case == "delivery_assignment":
                    return await s["fulfillment"].assign_delivery(
                        staff(ids),
                        ids["branch"],
                        order.id,
                        ids["admin" if index == 0 else "cook"],
                    )
                if case == "serve_local":
                    return await s["orders"].complete_local(
                        staff(ids), ids["branch"], order.id
                    )
                if case in {"cancel_kitchen", "cancel_payment"} and index == 0:
                    return await get_cancellation_service(session).review(
                        staff(ids),
                        ids["branch"],
                        cancellation.id,
                        RequestStatus.APPROVED,
                    )
                body, headers = signed_event(
                    initiation.attempt,
                    amount=str(order.total),
                    event="TEST-race-paid",
                    occurred_at=utc_now(),
                )
                return await s["payments"].webhook(
                    s["payments"].gateway.provider_code, body, headers
                )

            results = await race(factory, work)
            successes = [r for r in results if not isinstance(r, ApplicationError)]
            if case == "checkout_different_key":
                assert len(successes) == 1
            elif case == "cancel_kitchen":
                assert len(successes) >= 1
            else:
                assert len(successes) == 2, results
            async with factory() as session:
                if case == "cart_update":
                    cart = await services(session)["cart"].get_cart(owner(ids))
                    assert cart.items[0].quantity in {3, 4}
                    assert cart.total == 20 * cart.items[0].quantity
                elif case.startswith("checkout"):
                    assert (
                        await session.scalar(text("SELECT count(*) FROM orders")) == 1
                    )
                    if case == "checkout_same_key":
                        assert results[0].id == results[1].id
                elif case == "delivery_assignment":
                    assert (
                        await session.scalar(
                            text(
                                "SELECT count(*) FROM delivery_assignments "
                                "WHERE order_id=:id AND unassigned_at IS NULL "
                                "AND completed_at IS NULL"
                            ),
                            {"id": order.id},
                        )
                        == 1
                    )
                elif case in {"cancel_kitchen", "cancel_payment"}:
                    row = await services(session)["orders"].get(owner(ids), order.id)
                    assert row.status == "CANCELLED" and row.payment_status == "PAID"
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
                elif case == "cash_refund":
                    assert (
                        await session.scalar(
                            text("SELECT status FROM refunds WHERE id=:id"),
                            {"id": refund.id},
                        )
                        == "REFUNDED"
                    )
                    assert (
                        await session.scalar(
                            text(
                                "SELECT count(*) FROM audit_logs "
                                "WHERE action='REFUND_CASH_CONFIRMED'"
                            )
                        )
                        == 1
                    )
                elif case in {"kitchen", "pickup_release", "serve_local"}:
                    state = {
                        "kitchen": "PREPARING",
                        "pickup_release": "WAITING",
                        "serve_local": "SERVED",
                    }[case]
                    assert (
                        await session.scalar(
                            text(
                                "SELECT count(*) FROM order_status_history "
                                "WHERE order_id=:id AND to_status=:state"
                            ),
                            {"id": order.id, "state": state},
                        )
                        == 1
                    )
                else:
                    assert (
                        await session.scalar(
                            text(
                                "SELECT count(*) FROM payments "
                                "WHERE order_id=:id AND status='PAID'"
                            ),
                            {"id": order.id},
                        )
                        == 1
                    )

    asyncio.run(scenario())
