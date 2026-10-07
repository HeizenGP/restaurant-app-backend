import asyncio
from dataclasses import asdict, replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError

from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.application.errors import KitchenIntegrityError
from app.modules.kitchen.infrastructure.authorization import (
    SQLAlchemyKitchenAuthorization,
)
from app.modules.kitchen.infrastructure.orders import SQLAlchemyKitchenOrdersGateway
from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    StatusHistory,
)
from app.modules.orders.infrastructure.persistence.models import OrderStatusHistoryModel
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
)
from tests.modules.kitchen.fakes import NOW, context, record


def run(awaitable):
    return asyncio.run(awaitable)


def session():
    value = MagicMock()
    for name in ("execute", "flush", "commit", "rollback"):
        setattr(value, name, AsyncMock())
    return value


def result(*, rows=(), row=None, scalar=None):
    value = MagicMock()
    value.mappings.return_value.all.return_value = list(rows)
    value.mappings.return_value.one_or_none.return_value = row
    value.scalar_one_or_none.return_value = scalar
    return value


def sql(query):
    return str(
        query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).lower()


def projection_row(row):
    return {
        "id": row.id,
        "order_number": row.order_number,
        "branch_id": row.branch_id,
        "mode": row.mode.value,
        "status": row.status.value,
        "created_at": row.created_at,
        "confirmed_at": row.confirmed_at,
        "table_label": row.table_label,
        "requested_pickup_at": row.requested_pickup_at,
        "estimated_ready_at": row.estimated_ready_at,
        "estimated_delivery_at": row.estimated_delivery_at,
        "items": [
            asdict(item)
            | {"addon_options": [asdict(option) for option in item.addon_options]}
            for item in row.items
        ],
        "history": [
            {
                "id": str(entry.id),
                "from_status": entry.from_status.value if entry.from_status else None,
                "to_status": entry.to_status.value,
                "created_at": entry.created_at.isoformat(),
                "reason": entry.reason,
            }
            for entry in row.history
        ],
    }


@pytest.mark.parametrize("size", [0, 1, 50])
def test_queue_is_one_statement_independent_of_order_count(size):
    store = session()
    rows = [projection_row(record(number=index + 1)) for index in range(size)]
    store.execute.return_value = result(rows=rows)
    gateway = SQLAlchemyKitchenOrdersGateway(store)
    branch = uuid4()
    orders = run(gateway.queue(branch, KitchenQueueQuery()))
    assert len(orders) == size and store.execute.await_count == 1
    query = store.execute.call_args.args[0]
    statement = sql(query)
    assert str(branch) in statement and "orders.branch_id =" in statement
    assert "limit 101" in statement and "offset 0" in statement
    assert "jsonb_agg" in statement and "order_status_history" in statement
    assert "for update" not in statement and "for share" not in statement
    assert "pending_payment" not in statement and "scheduled" not in statement
    assert all(
        status in statement
        for status in ("waiting", "preparing", "ready", "ready_for_pickup")
    )
    assert "orders.confirmed_at is not null" in statement
    assert "orders.payment_status = 'paid'" in statement
    store.commit.assert_not_awaited()
    store.flush.assert_not_awaited()


def test_queue_filters_and_history_ordering_are_applied_before_limit():
    store = session()
    store.execute.return_value = result()
    run(
        SQLAlchemyKitchenOrdersGateway(store).queue(
            uuid4(),
            KitchenQueueQuery(
                mode=OrderMode.PICKUP,
                status=OrderStatus.READY_FOR_PICKUP,
                limit=20,
                offset=5,
            ),
        )
    )
    statement = sql(store.execute.call_args.args[0])
    assert "orders.mode = 'pickup'" in statement
    assert "orders.status = 'ready_for_pickup'" in statement
    assert "max(order_status_history.created_at)" in statement
    assert "order_status_history.to_status = orders.status" in statement
    assert "order by case" in statement and "nulls first" in statement
    assert "orders.order_number, orders.id" in statement
    assert "limit 21 offset 5" in statement


def test_projection_does_not_select_customer_financial_catalog_or_actor_data():
    store = session()
    store.execute.return_value = result()
    run(SQLAlchemyKitchenOrdersGateway(store).queue(uuid4(), KitchenQueueQuery()))
    statement = sql(store.execute.call_args.args[0])
    for field in (
        "customer_id",
        "customer_name",
        "customer_phone",
        "pickup_name",
        "pickup_phone",
        "address_line",
        "latitude",
        "longitude",
        "subtotal",
        "total",
        "price_snapshot",
        "qr_token",
        "idempotency_key",
        "request_fingerprint",
        "changed_by_user_id",
        " from products",
        " from product_presentations",
    ):
        assert field not in statement


@pytest.mark.parametrize("mode", list(OrderMode))
def test_operational_projection_uses_snapshots_and_history(mode):
    row = record(mode=mode)
    store = session()
    store.execute.return_value = result(row=projection_row(row))
    loaded = run(SQLAlchemyKitchenOrdersGateway(store).get_order(row.branch_id, row.id))
    assert loaded.items == row.items
    assert [entry.to_status for entry in loaded.history] == [OrderStatus.WAITING]
    assert loaded.history[0].created_at == row.history[0].created_at
    assert loaded.table_label == row.table_label
    assert loaded.estimated_delivery_at == row.estimated_delivery_at
    assert store.execute.await_count == 1


def test_operational_detail_id_and_branch_are_both_scoped_in_sql():
    store = session()
    store.execute.return_value = result()
    branch, order_id = uuid4(), uuid4()
    assert (
        run(SQLAlchemyKitchenOrdersGateway(store).get_order(branch, order_id)) is None
    )
    statement = sql(store.execute.call_args.args[0])
    assert str(branch) in statement and str(order_id) in statement
    assert "orders.id =" in statement and "orders.branch_id =" in statement


def test_orders_public_context_contract_locks_by_branch_without_financial_load():
    row = record()
    store = session()
    mapping = asdict(context(row))
    store.execute.return_value = result(row=mapping)
    loaded = run(
        SQLAlchemyOrderRepository(store).lock_preparation_order(row.branch_id, row.id)
    )
    assert loaded == context(row)
    assert store.execute.await_count == 1
    statement = sql(store.execute.call_args.args[0])
    assert "for update of orders" in statement and "orders.branch_id =" in statement
    assert "customer_id" not in statement and "subtotal" not in statement


def test_internal_context_contract_missing_order_is_none():
    store = session()
    store.execute.return_value = result()
    assert (
        run(SQLAlchemyOrderRepository(store).lock_preparation_order(uuid4(), uuid4()))
        is None
    )


def test_preparation_write_revalidates_graph_and_uses_conditional_update_append():
    row = record()
    store = session()
    store.execute.return_value = result(scalar=row.id)
    history = StatusHistory(
        from_status=row.status,
        to_status=OrderStatus.PREPARING,
        changed_by_user_id=uuid4(),
        reason="Kitchen started preparation",
        created_at=NOW,
    )
    run(
        SQLAlchemyOrderRepository(store).record_preparation_transition(
            context(row), history
        )
    )
    statement = sql(store.execute.call_args.args[0])
    assert "update orders set status='preparing'" in statement
    assert all(
        field in statement
        for field in (
            "orders.id =",
            "orders.branch_id =",
            "orders.status = 'waiting'",
            "orders.mode =",
            "orders.payment_status =",
            "confirmed_at is not null",
        )
    )
    assert "set payment_status" not in statement and "set confirmed_at" not in statement
    added = store.add.call_args.args[0]
    assert isinstance(added, OrderStatusHistoryModel)
    assert added.changed_by_user_id == history.changed_by_user_id
    assert added.from_status == "WAITING" and added.to_status == "PREPARING"
    store.flush.assert_awaited_once()
    store.commit.assert_not_awaited()


def test_lost_conditional_update_conflicts_before_history_insert():
    store = session()
    store.execute.return_value = result()
    row = record()
    history = StatusHistory(
        from_status=row.status,
        to_status=OrderStatus.PREPARING,
        changed_by_user_id=uuid4(),
        created_at=NOW,
    )
    with pytest.raises(OrderConflictError):
        run(
            SQLAlchemyOrderRepository(store).record_preparation_transition(
                context(row), history
            )
        )
    store.add.assert_not_called()


@pytest.mark.parametrize(
    "target", [OrderStatus.CANCELLED, OrderStatus.READY, OrderStatus.SERVED]
)
def test_invalid_internal_targets_do_not_execute_sql(target):
    store = session()
    row = record()
    history = StatusHistory(
        from_status=row.status,
        to_status=target,
        changed_by_user_id=uuid4(),
        created_at=NOW,
    )
    with pytest.raises(OrderRuleError):
        run(
            SQLAlchemyOrderRepository(store).record_preparation_transition(
                context(row), history
            )
        )
    store.execute.assert_not_awaited()


@pytest.mark.parametrize("error_type", [IntegrityError, OperationalError])
def test_history_flush_errors_propagate_safely_for_transaction_owner(error_type):
    store = session()
    row = record()
    store.execute.return_value = result(scalar=row.id)
    store.flush.side_effect = error_type(
        "private SQL", {"secret": "value"}, Exception("private DSN")
    )
    history = StatusHistory(
        from_status=row.status,
        to_status=OrderStatus.PREPARING,
        changed_by_user_id=uuid4(),
        created_at=NOW,
    )
    expected = OrderConflictError if error_type == IntegrityError else OperationalError
    with pytest.raises(expected) as caught:
        run(
            SQLAlchemyOrderRepository(store).record_preparation_transition(
                context(row), history
            )
        )
    if expected == OrderConflictError:
        assert "private" not in str(caught.value)
    store.commit.assert_not_awaited()


def test_kitchen_adapter_uses_public_orders_operations_and_same_session():
    store = session()
    gateway = SQLAlchemyKitchenOrdersGateway(store)
    gateway._orders = MagicMock()
    gateway._orders.lock_preparation_order = AsyncMock(return_value=None)
    gateway._orders.record_preparation_transition = AsyncMock()
    gateway._orders.commit = AsyncMock()
    gateway._orders.rollback = AsyncMock()
    row = record()
    assert run(gateway.lock_order(row.branch_id, row.id)) is None
    gateway._orders.lock_preparation_order.assert_awaited_once_with(
        row.branch_id, row.id
    )
    run(gateway.commit())
    run(gateway.rollback())
    gateway._orders.commit.assert_awaited_once()
    gateway._orders.rollback.assert_awaited_once()


def test_authorization_reuses_current_database_assignment_user_branch_permissions():
    store = session()
    store.execute.return_value = result(scalar=uuid4())
    user, branch = uuid4(), uuid4()
    assert run(
        SQLAlchemyKitchenAuthorization(store).has_permission(
            user, branch, "KITCHEN_MANAGE"
        )
    )
    statement = sql(store.execute.call_args.args[0])
    for predicate in (
        "staff_assignments.is_active is true",
        "staff_assignments.ended_at is null",
        "users.account_status = 'active'",
        "users.deleted_at is null",
        "branches.is_active is true",
        "branches.deleted_at is null",
        "roles.scope = 'branch'",
        "permissions.code = 'kitchen_manage'",
    ):
        assert predicate in statement
    assert str(user) in statement and str(branch) in statement
    assert "roles.code = 'admin'" not in statement


def test_corrupt_projection_is_safe_integrity_error():
    store = session()
    mapping = projection_row(record())
    mapping["history"][0]["created_at"] = "bad timestamp, private value"
    store.execute.return_value = result(row=mapping)
    with pytest.raises(KitchenIntegrityError) as caught:
        run(SQLAlchemyKitchenOrdersGateway(store).get_order(uuid4(), uuid4()))
    assert "private" not in str(caught.value)


def test_integration_fixture_builds_valid_orders_without_a_database(monkeypatch):
    from tests.integration.test_phase5_postgresql import insert_operational_fixtures

    store = session()
    store.scalar = AsyncMock(return_value=uuid4())
    created = []

    async def create(repository, order):
        created.append(order)
        return replace(order, order_number=len(created))

    monkeypatch.setattr(SQLAlchemyOrderRepository, "create", create)
    ids = {
        name: uuid4()
        for name in (
            "cart",
            "customer",
            "branch",
            "product",
            "presentation",
            "addon",
            "option",
        )
    }
    orders = run(insert_operational_fixtures(store, ids))
    assert {order.mode for order in orders} == set(OrderMode)
    assert all(order.status == OrderStatus.WAITING for order in orders)
    assert all(order.confirmed_at is not None for order in orders)
