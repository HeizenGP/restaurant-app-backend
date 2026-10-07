import asyncio
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.application.errors import (
    KitchenIntegrityError,
    KitchenInvalidTransitionError,
    KitchenOrderNotConfirmedError,
    KitchenOrderNotFoundError,
    KitchenPermissionDeniedError,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus
from tests.modules.kitchen.fakes import NOW, record


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize("who", ["user", "admin"])
def test_reads_are_permitted_without_any_writes(setup, who):
    principal = getattr(setup, who)
    assert run(
        setup.service.get_queue(principal, setup.branch, KitchenQueueQuery())
    ).waiting
    assert (
        run(setup.service.get_kitchen_order(principal, setup.branch, setup.row.id)).id
        == setup.row.id
    )
    assert setup.store.commits == setup.store.transitions == 0
    assert setup.gateway.calls == ["queue", "get"]


def test_view_permission_does_not_grant_preparation_operations(setup):
    setup.authorization.grants.remove(
        (setup.user.user_id, setup.branch, "KITCHEN_MANAGE")
    )
    assert run(
        setup.service.get_queue(setup.user, setup.branch, KitchenQueueQuery())
    ).waiting
    with pytest.raises(KitchenPermissionDeniedError):
        run(setup.service.start_preparation(setup.user, setup.branch, setup.row.id))


def test_manage_permission_does_not_implicitly_grant_view_permission(setup):
    setup.authorization.grants.remove(
        (setup.user.user_id, setup.branch, "KITCHEN_VIEW")
    )
    with pytest.raises(KitchenPermissionDeniedError):
        run(setup.service.get_queue(setup.user, setup.branch, KitchenQueueQuery()))
    assert (
        run(
            setup.service.start_preparation(setup.user, setup.branch, setup.row.id)
        ).status
        == OrderStatus.PREPARING
    )


@pytest.mark.parametrize(
    "operation", ["get_kitchen_order", "start_preparation", "mark_ready"]
)
def test_missing_order_is_404_without_any_transition(setup, operation):
    with pytest.raises(KitchenOrderNotFoundError):
        run(getattr(setup.service, operation)(setup.user, setup.branch, uuid4()))
    assert setup.store.transitions == setup.store.commits == 0


@pytest.mark.parametrize("who", ["guest", "customer", "foreign"])
@pytest.mark.parametrize(
    "operation", ["get_queue", "get_kitchen_order", "start_preparation", "mark_ready"]
)
def test_principals_without_current_branch_permission_cannot_operate(
    setup, who, operation
):
    args = (KitchenQueueQuery(),) if operation == "get_queue" else (setup.row.id,)
    with pytest.raises(KitchenPermissionDeniedError):
        run(getattr(setup.service, operation)(getattr(setup, who), setup.branch, *args))
    assert "lock" not in setup.gateway.calls and "queue" not in setup.gateway.calls


@pytest.mark.parametrize(
    "condition", ["inactive", "ended", "blocked", "deleted", "inactive_branches"]
)
def test_current_permission_state_is_checked_each_request(setup, condition):
    field = getattr(setup.authorization, condition)
    field.add(setup.branch if condition == "inactive_branches" else setup.user.user_id)
    with pytest.raises(KitchenPermissionDeniedError):
        run(setup.service.start_preparation(setup.user, setup.branch, setup.row.id))


@pytest.mark.parametrize(
    "operation", ["get_queue", "get_kitchen_order", "start_preparation", "mark_ready"]
)
def test_authorized_user_has_no_global_branch_access(setup, operation):
    args = (KitchenQueueQuery(),) if operation == "get_queue" else (setup.row.id,)
    with pytest.raises(KitchenPermissionDeniedError):
        run(getattr(setup.service, operation)(setup.user, uuid4(), *args))


@pytest.mark.parametrize(
    "operation", ["get_kitchen_order", "start_preparation", "mark_ready"]
)
def test_foreign_order_id_is_not_revealed_after_branch_authorization(setup, operation):
    row = setup.store.add(record(branch_id=uuid4()))
    with pytest.raises(KitchenOrderNotFoundError):
        run(getattr(setup.service, operation)(setup.user, setup.branch, row.id))


def test_queue_contains_only_confirmed_operational_states(setup):
    setup.store.orders.clear()
    for status in OrderStatus:
        mode = (
            OrderMode.PICKUP
            if status
            in {
                OrderStatus.SCHEDULED,
                OrderStatus.READY_FOR_PICKUP,
                OrderStatus.PICKED_UP,
            }
            else OrderMode.DELIVERY
            if status in {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED}
            else OrderMode.LOCAL
        )
        setup.store.add(record(branch_id=setup.branch, status=status, mode=mode))
    setup.store.add(record(branch_id=setup.branch, confirmed=False))
    setup.store.add(
        record(
            branch_id=setup.branch,
            mode=OrderMode.DELIVERY,
            payment_status=PaymentStatus.PENDING,
        )
    )
    queue = run(setup.service.get_queue(setup.user, setup.branch, KitchenQueueQuery()))
    assert {
        order.status for order in (*queue.waiting, *queue.preparing, *queue.ready)
    } == {
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.READY_FOR_PICKUP,
    }
    assert sum(map(len, (queue.waiting, queue.preparing, queue.ready))) == 4
    assert setup.store.commits == setup.store.transitions == 0


def test_queue_pagination_and_filters_have_no_side_effects(setup):
    for number in range(2, 8):
        setup.store.add(record(branch_id=setup.branch, number=number))
    page = run(
        setup.service.get_queue(
            setup.user, setup.branch, KitchenQueueQuery(limit=2, offset=2)
        )
    )
    assert [row.order_number for row in page.waiting] == [3, 4] and page.has_more
    empty = run(
        setup.service.get_queue(
            setup.user, setup.branch, KitchenQueueQuery(mode=OrderMode.PICKUP)
        )
    )
    assert not empty.waiting and not empty.has_more
    assert setup.store.commits == 0


def test_start_is_atomic_actor_owned_and_retry_safe(setup):
    initial = deepcopy(setup.row)
    first = run(setup.service.start_preparation(setup.user, setup.branch, setup.row.id))
    second = run(
        setup.service.start_preparation(setup.user, setup.branch, setup.row.id)
    )
    assert first.status == second.status == OrderStatus.PREPARING
    row = setup.store.orders[setup.row.id]
    assert len(row.history) == 2 and setup.store.transitions == 1
    history = row.history[-1]
    assert history.changed_by_user_id == setup.user.user_id
    assert history.from_status == OrderStatus.WAITING and history.created_at == NOW
    assert history.reason == "Kitchen started preparation"
    assert row.confirmed_at == initial.confirmed_at
    assert row.payment_status == initial.payment_status
    assert setup.store.commits == 2


@pytest.mark.parametrize(
    "mode,target",
    [
        (OrderMode.LOCAL, OrderStatus.READY),
        (OrderMode.DELIVERY, OrderStatus.READY),
        (OrderMode.PICKUP, OrderStatus.READY_FOR_PICKUP),
    ],
)
def test_mark_ready_respects_mode_and_retry_does_not_duplicate(setup, mode, target):
    row = setup.store.add(
        record(branch_id=setup.branch, mode=mode, status=OrderStatus.PREPARING)
    )
    first = run(setup.service.mark_ready(setup.user, setup.branch, row.id))
    second = run(setup.service.mark_ready(setup.admin, setup.branch, row.id))
    assert first.status == second.status == target
    persisted = setup.store.orders[row.id]
    assert len(persisted.history) == 3 and setup.store.transitions == 1
    assert persisted.history[-1].changed_by_user_id == setup.user.user_id


@pytest.mark.parametrize("operation", ["start_preparation", "mark_ready"])
@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PENDING_CASH_CONFIRMATION,
        OrderStatus.SCHEDULED,
        OrderStatus.CANCELLED,
        OrderStatus.SERVED,
        OrderStatus.PICKED_UP,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
    ],
)
def test_non_operational_states_never_transition(setup, operation, status):
    row = setup.store.add(record(branch_id=setup.branch, status=status))
    with pytest.raises(KitchenInvalidTransitionError):
        run(getattr(setup.service, operation)(setup.user, setup.branch, row.id))
    assert row.status == status and setup.store.transitions == 0


@pytest.mark.parametrize(
    "operation,status",
    [
        ("start_preparation", OrderStatus.READY),
        ("mark_ready", OrderStatus.WAITING),
    ],
)
def test_no_skips_or_backwards_steps(setup, operation, status):
    row = setup.store.add(record(branch_id=setup.branch, status=status))
    with pytest.raises(KitchenInvalidTransitionError):
        run(getattr(setup.service, operation)(setup.user, setup.branch, row.id))


@pytest.mark.parametrize("unconfirmed", ["timestamp", "payment"])
def test_unconfirmed_orders_cannot_be_prepared(setup, unconfirmed):
    row = setup.store.add(
        record(
            branch_id=setup.branch,
            mode=OrderMode.DELIVERY,
            confirmed=unconfirmed != "timestamp",
            payment_status=PaymentStatus.PENDING
            if unconfirmed == "payment"
            else PaymentStatus.PAID,
        )
    )
    with pytest.raises(KitchenOrderNotConfirmedError):
        run(setup.service.start_preparation(setup.user, setup.branch, row.id))


@pytest.mark.parametrize("failure", ["fail_history", "fail_commit"])
def test_transaction_failure_rolls_back_status_and_history(setup, failure):
    before = deepcopy(setup.row)
    setattr(setup.gateway, failure, True)
    with pytest.raises(RuntimeError):
        run(setup.service.start_preparation(setup.user, setup.branch, setup.row.id))
    row = setup.store.orders[setup.row.id]
    assert row.status == before.status and row.history == before.history
    assert setup.store.commits == 0 and setup.store.rollbacks == 1
    assert setup.gateway.locked is None


def test_inconsistent_history_is_explicit_and_blocks_writes(setup):
    setup.row.history = ()
    for operation in ("get_queue", "get_kitchen_order", "start_preparation"):
        args = (KitchenQueueQuery(),) if operation == "get_queue" else (setup.row.id,)
        with pytest.raises(KitchenIntegrityError):
            run(getattr(setup.service, operation)(setup.user, setup.branch, *args))
    assert setup.store.orders[setup.row.id].status == OrderStatus.WAITING
    assert setup.store.transitions == 0


@pytest.mark.parametrize(
    "operation,status",
    [
        ("start_preparation", OrderStatus.WAITING),
        ("mark_ready", OrderStatus.PREPARING),
    ],
)
def test_two_simultaneous_requests_make_one_real_transition(setup, operation, status):
    async def verify():
        setup.row.status = status
        if status == OrderStatus.PREPARING:
            setup.row.history = record(status=status).history
        _, first = setup.fork()
        _, second = setup.fork()
        results = await asyncio.gather(
            getattr(first, operation)(setup.user, setup.branch, setup.row.id),
            getattr(second, operation)(setup.admin, setup.branch, setup.row.id),
        )
        assert results[0].status == results[1].status
        assert setup.store.transitions == 1
        assert len(setup.store.orders[setup.row.id].history) == (
            2 if status == OrderStatus.WAITING else 3
        )

    run(verify())


def test_start_and_ready_are_serialized_without_skipping_history(setup):
    async def verify():
        _, start = setup.fork()
        _, ready = setup.fork()
        results = await asyncio.gather(
            start.start_preparation(setup.user, setup.branch, setup.row.id),
            ready.mark_ready(setup.admin, setup.branch, setup.row.id),
            return_exceptions=True,
        )
        assert not isinstance(results[0], Exception)
        assert not isinstance(results[1], Exception)
        row = setup.store.orders[setup.row.id]
        assert [entry.to_status for entry in row.history] == [
            OrderStatus.WAITING,
            OrderStatus.PREPARING,
            OrderStatus.READY,
        ]

    run(verify())


def test_active_detail_policy_excludes_non_operational_orders(setup):
    row = setup.store.add(record(branch_id=setup.branch, status=OrderStatus.SERVED))
    with pytest.raises(KitchenOrderNotFoundError):
        run(setup.service.get_kitchen_order(setup.user, setup.branch, row.id))


def test_real_checkout_snapshots_survive_catalog_changes(setup):
    from tests.modules.kitchen.fakes import snapshot
    from tests.modules.orders.fakes import orders_setup

    async def verify():
        orders = await orders_setup()
        order = await orders.service.create(
            orders.cart.guest, "kitchen-snapshot", orders.local()
        )
        released = await orders.service.confirm_cash_release(
            orders.cart.admin, order.id
        )
        original = released.items[0].product_name_snapshot
        product = orders.cart.catalog_repository.products[orders.cart.product.id]
        orders.cart.catalog_repository.products[product.id] = replace(
            product, name="Renamed"
        )
        from app.modules.kitchen.domain.models import KitchenItem

        row = record(branch_id=setup.branch)
        row.items = tuple(
            KitchenItem(
                product_name_snapshot=item.product_name_snapshot,
                presentation_name_snapshot=item.presentation_name_snapshot,
                quantity=item.quantity,
                notes=item.notes,
            )
            for item in released.items
        )
        setup.store.add(row)
        card = await setup.service.get_kitchen_order(setup.user, setup.branch, row.id)
        assert card.items[0].product_name_snapshot == original != "Renamed"
        assert snapshot(row).items == card.items

    run(verify())
