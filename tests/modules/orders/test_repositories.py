import asyncio
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError

from app.modules.cart.domain.models import Cart
from app.modules.orders.application.errors import (
    OrderConflictError,
    OrderUniqueConflictError,
)
from app.modules.orders.infrastructure.cart import SQLAlchemyCartCheckoutGateway
from app.modules.orders.infrastructure.customers import (
    SQLAlchemyCustomerCheckoutGateway,
)
from app.modules.orders.infrastructure.persistence.models import (
    OrderAddonOptionModel,
    OrderItemModel,
    OrderLocalDetailsModel,
    OrderModel,
    OrderStatusHistoryModel,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyOrderSettingsRepository,
    flush,
    settings_from_json,
    settings_json,
)
from app.modules.orders.infrastructure.scheduling import SQLAlchemyKitchenLoadEstimator


class Rows(list):
    def all(self):
        return list(self)


def result(rows=(), scalar=None):
    value = MagicMock()
    value.scalars.return_value = Rows(rows)
    value.all.return_value = list(rows)
    value.scalar_one_or_none.return_value = scalar
    value.scalar_one.return_value = scalar
    return value


def session():
    value = MagicMock()
    for name in ("execute", "flush", "refresh", "commit", "rollback", "get"):
        setattr(value, name, AsyncMock())
    value.get.return_value = None
    return value


def sql(query):
    return str(query.compile(dialect=postgresql.dialect())).lower()


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.mark.parametrize("operation", ["get", "list", "idempotency"])
def test_order_reads_scope_ownership_in_the_query_and_never_commit(operation):
    async def verify():
        store = session()
        store.execute.return_value = result()
        repository = SQLAlchemyOrderRepository(store)
        customer, order_id = uuid4(), uuid4()
        if operation == "get":
            assert await repository.get_owned(customer, order_id) is None
        elif operation == "list":
            assert await repository.list_owned(customer, 20, 4) == []
        else:
            assert await repository.by_idempotency(customer, "request") is None
        query = store.execute.call_args.args[0]
        statement = sql(query)
        assert "orders.customer_id =" in statement
        if operation == "get":
            assert "orders.id =" in statement
        elif operation == "list":
            assert "order by orders.created_at desc, orders.id desc" in statement
            assert "limit" in statement and "offset" in statement
        else:
            assert "orders.idempotency_key =" in statement
        store.commit.assert_not_awaited()
        store.flush.assert_not_awaited()

    run(verify())


def test_order_admin_query_locks_current_order_before_transition():
    store = session()
    store.execute.return_value = result()
    assert run(SQLAlchemyOrderRepository(store).lock_order(uuid4())) is None
    assert "for update" in sql(store.execute.call_args.args[0])


def test_customer_context_lock_and_address_owner_query():
    store = session()
    store.execute.return_value = result()
    gateway = SQLAlchemyCustomerCheckoutGateway(store)
    assert run(gateway.lock_customer(uuid4())) is None
    assert "for update" in sql(store.execute.call_args.args[0])
    assert run(gateway.address(uuid4(), uuid4())) is None
    statement = sql(store.execute.call_args.args[0])
    assert (
        "customer_addresses.customer_id =" in statement
        and "customer_addresses.id =" in statement
    )
    assert "for share" in statement


def test_cart_checkout_has_parent_lock_and_scoped_status_transition():
    store = session()
    store.execute.return_value = result()
    gateway = SQLAlchemyCartCheckoutGateway(store, MagicMock())
    assert run(gateway.get_and_lock_active_cart(uuid4())) is None
    statement = sql(store.execute.call_args.args[0])
    assert (
        "for update" in statement
        and "carts.customer_id =" in statement
        and "carts.status =" in statement
    )
    cart = Cart(customer_id=uuid4(), branch_id=uuid4())
    store.execute.return_value = result(scalar=cart.id)
    run(gateway.mark_checked_out(cart))
    query = store.execute.call_args.args[0]
    assert query.compile().params["status"] == "CHECKED_OUT"
    statement = sql(query)
    assert (
        "update carts" in statement
        and "carts.customer_id =" in statement
        and "carts.status =" in statement
    )
    store.commit.assert_not_awaited()


def test_cart_checkout_lost_transition_is_conflict():
    store = session()
    store.execute.return_value = result()
    gateway = SQLAlchemyCartCheckoutGateway(store, MagicMock())
    with pytest.raises(OrderConflictError):
        run(gateway.mark_checked_out(Cart(customer_id=uuid4(), branch_id=uuid4())))


def test_checkout_batch_uses_one_catalog_load_for_many_lines(setup):
    async def verify():
        cart = await setup.cart.repository.find_active(setup.cart.guest.customer_id)
        item = next(iter(setup.cart.repository.items.values()))
        store = session()
        gateway = SQLAlchemyCartCheckoutGateway(store, setup.cart.catalog)
        gateway._carts = MagicMock()
        gateway._carts.list_items = AsyncMock(
            return_value=[replace(item, id=uuid4()) for _ in range(10)]
        )
        aggregates = await setup.cart.catalog_repository.public_products(cart.branch_id)
        gateway._catalog_repository = MagicMock()
        gateway._catalog_repository.public_products = AsyncMock(return_value=aggregates)
        store.execute.side_effect = [
            result(),
            result(scalar=cart.branch_id),
            result([setup.cart.category.id]),
            result([setup.cart.product]),
        ]
        lines = await gateway.validate_for_checkout(cart)
        assert len(lines) == 10
        gateway._catalog_repository.public_products.assert_awaited_once_with(
            cart.branch_id, product_ids=(item.product_id,)
        )
        statements = [sql(call.args[0]) for call in store.execute.call_args_list]
        assert "for update" in statements[0]
        assert all("for share" in statement for statement in statements[1:])
        assert lines[0].product_name_snapshot == "Aeropuerto"
        store.commit.assert_not_awaited()
        store.flush.assert_not_awaited()

    run(verify())


def test_catalog_category_race_rejects_without_new_out_of_order_lock(setup):
    async def verify():
        cart = await setup.cart.repository.find_active(setup.cart.guest.customer_id)
        store = session()
        gateway = SQLAlchemyCartCheckoutGateway(store, setup.cart.catalog)
        gateway._carts = MagicMock()
        gateway._carts.list_items = AsyncMock(
            return_value=list(setup.cart.repository.items.values())
        )
        store.execute.side_effect = [
            result(),
            result(scalar=cart.branch_id),
            result([uuid4()]),
            result([setup.cart.product]),
        ]
        with pytest.raises(OrderConflictError):
            await gateway.validate_for_checkout(cart)
        assert store.execute.await_count == 4

    run(verify())


@pytest.mark.parametrize("update", [False, True])
def test_settings_locks_cover_missing_row_without_checkout_lock_upgrade(update):
    store = session()
    store.execute.side_effect = [result(), result()]
    settings = run(
        SQLAlchemyOrderSettingsRepository(store).get_settings(
            uuid4(), lock=True, for_update=update
        )
    )
    statements = [sql(call.args[0]) for call in store.execute.call_args_list]
    assert all(
        ("for update" if update else "for share") in query for query in statements
    )
    assert settings.default_prep_minutes == 20
    store.commit.assert_not_awaited()
    store.flush.assert_not_awaited()


@pytest.mark.parametrize("resource", ["table", "zone"])
def test_admin_resource_queries_scope_branch_and_lock(resource):
    store = session()
    store.execute.return_value = result()
    repo = SQLAlchemyOrderSettingsRepository(store)
    result_value = run(
        repo.get_table(uuid4(), uuid4())
        if resource == "table"
        else repo.get_zone(uuid4(), uuid4())
    )
    assert result_value is None
    query = sql(store.execute.call_args.args[0])
    assert "branch_id =" in query and "for update" in query


def test_zone_resolution_normalizes_district_and_prioritizes_global_free_policy():
    store = session()
    store.execute.return_value = result()
    run(SQLAlchemyOrderSettingsRepository(store).resolve_zone(uuid4(), " TARAPOTO "))
    query = store.execute.call_args.args[0]
    statement = sql(query)
    assert (
        "order by case" in statement
        and "branch_id is null" in statement
        and "is_free is true" in statement
    )
    assert "for share" in statement
    assert "TARAPOTO" in query.compile().params.values()


def test_future_due_pickup_query_is_paid_scheduled_and_time_bounded(setup):
    store = session()
    store.execute.return_value = result()
    assert run(SQLAlchemyOrderRepository(store).pickup_due_for_release(setup.now)) == []
    query = store.execute.call_args.args[0]
    params = query.compile().params.values()
    assert "SCHEDULED" in params and "PAID" in params
    assert "calculated_kitchen_release_at <=" in sql(query)


def test_estimator_counts_only_confirmed_queue_statuses(setup):
    store = session()
    store.execute.return_value = result(scalar=3)
    repo = SQLAlchemyOrderRepository(store)
    settings = setup.store.settings.get(setup.cart.branch)
    if settings is None:
        from app.modules.orders.domain.models import BranchOrderSettings

        settings = BranchOrderSettings(branch_id=setup.cart.branch)
    estimate = run(
        SQLAlchemyKitchenLoadEstimator(repo).estimate(setup.cart.branch, settings)
    )
    assert estimate.total_minutes == 35 and estimate.queue_depth == 3
    query = store.execute.call_args.args[0]
    params = query.compile().params
    assert params["status_1"] == ["WAITING", "PREPARING"]


@pytest.mark.parametrize(
    "name",
    ["uq_orders_source_cart", "uq_orders_customer_idempotency", "ck_orders_totals"],
)
def test_flush_maps_integrity_without_leaking_sql_or_payload(name):
    store = session()
    original = Exception("private database message")
    original.constraint_name = name
    store.flush.side_effect = IntegrityError(
        "private sql", {"private": "data"}, original
    )
    expected = (
        OrderUniqueConflictError
        if name.startswith("uq_orders_")
        else OrderConflictError
    )
    with pytest.raises(expected) as caught:
        run(flush(store))
    assert "private" not in str(caught.value)


def test_database_unavailable_is_not_disguised_as_business_conflict():
    store = session()
    store.flush.side_effect = OperationalError("query", {}, Exception("offline"))
    with pytest.raises(OperationalError):
        run(flush(store))


@pytest.mark.parametrize("mode", ["LOCAL", "PICKUP", "DELIVERY"])
def test_order_insert_and_batched_historical_load_never_commit_implicitly(setup, mode):
    async def verify():
        from app.modules.orders.application.dtos import OrderCreate
        from app.modules.orders.domain.models import OrderMode
        from app.modules.orders.infrastructure.persistence.models import (
            OrderDeliveryDetailsModel,
            OrderPickupDetailsModel,
            OrderScheduleCalculationModel,
        )

        command = (
            setup.local()
            if mode == "LOCAL"
            else (
                OrderCreate(
                    mode=OrderMode.PICKUP,
                    requested_pickup_at=setup.now + timedelta(hours=2),
                )
                if mode == "PICKUP"
                else setup.delivery()
            )
        )
        order = await setup.service.create(setup.cart.guest, "repository", command)
        store = session()

        async def refresh(row):
            row.order_number = 123

        store.refresh.side_effect = refresh
        repo = SQLAlchemyOrderRepository(store)
        saved = await repo.create(replace(order, order_number=None))
        assert saved.order_number == 123
        models = [call.args[0] for call in store.add.call_args_list]
        counts = Counter(type(row) for row in models)
        assert (
            counts[OrderModel]
            == counts[OrderItemModel]
            == counts[OrderStatusHistoryModel]
            == 1
        )
        assert counts[OrderLocalDetailsModel] == (1 if mode == "LOCAL" else 0)
        assert all(
            row.branch_id == order.branch_id
            for row in models
            if isinstance(row, OrderModel)
        )
        store.commit.assert_not_awaited()
        mapping = {
            cls: [row for row in models if isinstance(row, cls)]
            for cls in (
                OrderModel,
                OrderItemModel,
                OrderAddonOptionModel,
                OrderStatusHistoryModel,
                OrderLocalDetailsModel,
                OrderPickupDetailsModel,
                OrderDeliveryDetailsModel,
                OrderScheduleCalculationModel,
            )
        }
        store.execute.side_effect = [
            result(mapping[OrderModel]),
            result(mapping[OrderItemModel]),
            result(mapping[OrderAddonOptionModel]),
            result(mapping[OrderStatusHistoryModel]),
            result(mapping[OrderLocalDetailsModel]),
            result(mapping[OrderPickupDetailsModel]),
            result(mapping[OrderDeliveryDetailsModel]),
            result(mapping[OrderScheduleCalculationModel]),
        ]
        loaded = await repo.get_owned(order.customer_id, order.id)
        assert loaded.items == order.items
        assert loaded.local_details == order.local_details
        assert loaded.pickup_details == order.pickup_details
        assert loaded.delivery_details == order.delivery_details
        assert loaded.schedule_calculation == order.schedule_calculation
        assert loaded.branch_settings_snapshot == order.branch_settings_snapshot
        assert store.execute.await_count == 8
        assert (
            settings_from_json(settings_json(order.branch_settings_snapshot))
            == order.branch_settings_snapshot
        )

    run(verify())
