import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.orders.application.errors import OrderConflictError, OrderNotFoundError
from app.modules.orders.domain.models import OrderStatus, StatusHistory


async def ready_order(setup):
    # OrdersSetup already prepares the active cart and its item.
    order = await setup.service.create(setup.cart.guest, "phase12-local", setup.local())
    histories = list(order.history)
    previous = order.status
    for target in (OrderStatus.WAITING, OrderStatus.PREPARING, OrderStatus.READY):
        histories.append(
            StatusHistory(
                from_status=previous,
                to_status=target,
                changed_by_user_id=setup.cart.admin.user_id,
                created_at=setup.now,
            )
        )
        previous = target
    order = replace(
        order,
        status=OrderStatus.READY,
        confirmed_at=setup.now,
        history=tuple(histories),
    )
    setup.store.orders[order.id] = order
    setup.service._audit = AsyncMock()
    return order


def test_local_completion_retries_without_duplicate_history_or_audit(setup):
    async def scenario():
        order = await ready_order(setup)
        first = await setup.service.complete_local(
            setup.cart.admin, order.branch_id, order.id
        )
        second = await setup.service.complete_local(
            setup.cart.admin, order.branch_id, order.id
        )
        assert first == second and first.status == OrderStatus.SERVED
        assert first.payment_status == order.payment_status
        assert first.total == order.total and first.items == order.items
        assert first.history[-1].from_status == OrderStatus.READY
        assert first.history[-1].changed_by_user_id == setup.cart.admin.user_id
        setup.service._audit.record.assert_awaited_once()

    asyncio.run(scenario())


def test_audit_failure_rolls_back_local_state_and_history(setup):
    async def scenario():
        order = await ready_order(setup)
        setup.service._audit.record.side_effect = RuntimeError("TEST audit unavailable")
        with pytest.raises(RuntimeError):
            await setup.service.complete_local(
                setup.cart.admin, order.branch_id, order.id
            )
        assert setup.store.orders[order.id] == order

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status", [OrderStatus.WAITING, OrderStatus.PREPARING, OrderStatus.CANCELLED]
)
def test_local_cannot_skip_states_or_reactivate_cancelled(setup, status):
    async def scenario():
        order = await ready_order(setup)
        setup.store.orders[order.id] = replace(order, status=status)
        with pytest.raises(OrderConflictError):
            await setup.service.complete_local(
                setup.cart.admin, order.branch_id, order.id
            )
        setup.service._audit.record.assert_not_awaited()

    asyncio.run(scenario())


def test_local_completion_branch_predicate_returns_not_found(setup):
    async def scenario():
        order = await ready_order(setup)
        branch = uuid4()
        setup.store.grants.add((setup.cart.admin.user_id, branch, "ORDER_MANAGE"))
        with pytest.raises(OrderNotFoundError):
            await setup.service.complete_local(setup.cart.admin, branch, order.id)

    asyncio.run(scenario())


@pytest.mark.parametrize("who", ["guest", "registered", "staff", "foreign_admin"])
def test_only_branch_admin_can_serve_local_over_http(api, who):
    order = asyncio.run(ready_order(api.setup))
    target = (
        f"/api/v1/admin/orders/branches/{order.branch_id}/orders/{order.id}/serve-local"
    )
    assert api.client.post(target, headers=api.headers(who)).status_code == 403
    assert api.setup.store.orders[order.id].status == OrderStatus.READY


def test_local_completion_real_http_retry_and_mass_assignment(api):
    order = asyncio.run(ready_order(api.setup))
    target = (
        f"/api/v1/admin/orders/branches/{order.branch_id}/orders/{order.id}/serve-local"
    )
    assert api.client.post(target).status_code == 401
    assert (
        api.client.post(
            target, headers=api.headers("admin"), json={"status": "SERVED"}
        ).status_code
        == 422
    )
    first = api.client.post(target, headers=api.headers("admin"))
    assert first.status_code == 200 and first.json()["status"] == "SERVED"
    assert api.client.post(target, headers=api.headers("admin")).json() == first.json()
    api.setup.service._audit.record.assert_awaited_once()
