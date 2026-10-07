from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.modules.cart.application.errors import (
    ActiveCartExistsError,
    CartConflictError,
    CartItemNotFoundError,
)
from app.modules.cart.domain.models import Cart, CartItem
from app.modules.cart.infrastructure.persistence.models import (
    CartItemAddonOptionModel,
    CartItemModel,
    CartModel,
)
from app.modules.cart.infrastructure.persistence.repositories import (
    SQLAlchemyCartRepository,
)


def result(rows=(), scalar=None):
    value = MagicMock()
    value.all.return_value = list(rows)
    value.scalar_one_or_none.return_value = scalar
    value.scalars.return_value.all.return_value = list(rows)
    return value


def session():
    value = MagicMock()
    for name in ("execute", "flush", "refresh", "commit", "rollback", "get"):
        setattr(value, name, AsyncMock())
    return value


def sql(statement):
    return str(statement.compile(dialect=postgresql.dialect())).lower()


def item_model(cart_id):
    return CartItemModel(
        cart_id=cart_id,
        product_id=uuid4(),
        presentation_id=uuid4(),
        quantity=2,
        notes=None,
        base_price_snapshot=Decimal("1.00"),
        presentation_price_snapshot=Decimal("1.00"),
        addons_price_snapshot=Decimal("0.00"),
        unit_price_snapshot=Decimal("1.00"),
    )


@pytest.mark.parametrize("lock", [False, True])
def test_find_active_filters_customer_and_status_and_locks_fresh_state(lock):
    async def scenario():
        store = session()
        store.execute.return_value = result()
        repository = SQLAlchemyCartRepository(store)
        assert await repository.find_active(uuid4(), lock=lock) is None
        query = store.execute.call_args.args[0]
        compiled = sql(query)
        assert "carts.customer_id =" in compiled and "carts.status =" in compiled
        assert ("for update" in compiled) == lock
        if lock:
            assert query.get_execution_options()["populate_existing"] is True

    import asyncio

    asyncio.run(scenario())


def test_read_active_loads_fifty_items_and_options_in_one_consistent_query():
    async def scenario():
        store = session()
        cart = CartModel(customer_id=uuid4(), branch_id=uuid4())
        rows = []
        for _ in range(50):
            item = item_model(cart.id)
            option = CartItemAddonOptionModel(
                cart_item_id=item.id,
                product_addon_id=uuid4(),
                product_addon_option_id=uuid4(),
                additional_price_snapshot=Decimal("0.00"),
            )
            rows.append((cart, item, option))
        store.execute.return_value = result(rows)
        state = await SQLAlchemyCartRepository(store).read_active(cart.customer_id)
        assert len(state[1]) == 50 and all(
            len(item.selected_options) == 1 for item in state[1]
        )
        store.execute.assert_awaited_once()
        statement = sql(store.execute.call_args.args[0])
        assert statement.count("left outer join") == 2
        assert "carts.customer_id =" in statement and "carts.status =" in statement
        assert "for update" not in statement and "update " not in statement
        store.commit.assert_not_awaited()
        store.flush.assert_not_awaited()

    import asyncio

    asyncio.run(scenario())


@pytest.mark.parametrize("exists", [False, True])
def test_read_active_empty_or_missing_cart(exists):
    async def scenario():
        store = session()
        cart = CartModel(customer_id=uuid4(), branch_id=uuid4())
        store.execute.return_value = result([(cart, None, None)] if exists else [])
        state = await SQLAlchemyCartRepository(store).read_active(cart.customer_id)
        assert state[1] == () if exists else state is None

    import asyncio

    asyncio.run(scenario())


def test_list_items_uses_two_batches_and_deterministic_order_with_owner_scope():
    async def scenario():
        store = session()
        cart = Cart(customer_id=uuid4(), branch_id=uuid4())
        items = [item_model(cart.id) for _ in range(20)]
        store.execute.side_effect = [result(items), result([])]
        records = await SQLAlchemyCartRepository(store).list_items(cart)
        assert len(records) == 20 and store.execute.await_count == 2
        root, options = [sql(call.args[0]) for call in store.execute.call_args_list]
        assert (
            "join carts" in root
            and "carts.customer_id =" in root
            and "carts.status =" in root
        )
        assert "order by cart_items.created_at, cart_items.id" in root
        assert "cart_item_addon_options.cart_item_id in" in options

    import asyncio

    asyncio.run(scenario())


def test_get_item_is_scoped_to_cart_customer_and_locks_only_child_after_parent():
    async def scenario():
        store = session()
        store.execute.return_value = result()
        cart = Cart(customer_id=uuid4(), branch_id=uuid4())
        assert (
            await SQLAlchemyCartRepository(store).get_item(cart, uuid4(), lock=True)
            is None
        )
        query = store.execute.call_args.args[0]
        compiled = sql(query)
        assert (
            "carts.customer_id =" in compiled
            and "carts.id =" in compiled
            and "cart_items.id =" in compiled
        )
        assert "for update of cart_items" in compiled
        assert query.get_execution_options()["populate_existing"] is True

    import asyncio

    asyncio.run(scenario())


def test_create_and_abandon_cart_refresh_but_do_not_commit():
    async def scenario():
        store = session()
        cart = Cart(customer_id=uuid4(), branch_id=uuid4())
        repository = SQLAlchemyCartRepository(store)
        assert (await repository.create_cart(cart)).customer_id == cart.customer_id
        store.refresh.assert_awaited_once()
        await repository.abandon_cart(cart)
        statement = sql(store.execute.call_args.args[0])
        assert (
            "update carts" in statement
            and "carts.customer_id =" in statement
            and "carts.status =" in statement
        )
        store.commit.assert_not_awaited()

    import asyncio

    asyncio.run(scenario())


def test_item_delete_is_owned_and_cascade_is_defined():
    async def scenario():
        store = session()
        cart = Cart(customer_id=uuid4(), branch_id=uuid4())
        await SQLAlchemyCartRepository(store).delete_item(cart, uuid4())
        statement = sql(store.execute.call_args.args[0])
        assert "delete from cart_items" in statement and "exists" in statement
        assert (
            "carts.customer_id =" in statement and "cart_items.cart_id =" in statement
        )
        fk = next(iter(CartItemAddonOptionModel.__table__.c.cart_item_id.foreign_keys))
        assert fk.ondelete == "CASCADE"
        store.commit.assert_not_awaited()

    import asyncio

    asyncio.run(scenario())


def test_touch_cart_uses_trigger_not_app_timestamp():
    async def scenario():
        store = session()
        cart = Cart(customer_id=uuid4(), branch_id=uuid4())
        store.get.return_value = CartModel(
            id=cart.id, customer_id=cart.customer_id, branch_id=cart.branch_id
        )
        await SQLAlchemyCartRepository(store).touch_cart(cart)
        statement = sql(store.execute.call_args.args[0])
        assert "set status=carts.status" in statement and "updated_at=" not in statement
        store.refresh.assert_awaited_once()

    import asyncio

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["flush", "commit"])
@pytest.mark.parametrize(
    "constraint,error",
    [
        ("uq_carts_active_customer", ActiveCartExistsError),
        ("internal-secret-constraint", CartConflictError),
    ],
)
def test_integrity_is_translated_without_constraint_sql_or_credentials(
    operation, constraint, error
):
    async def scenario():
        class DriverError(Exception):
            pass

        original = DriverError("SQL and DSN must not escape")
        original.diag = SimpleNamespace(constraint_name=constraint)
        store = session()
        getattr(store, operation).side_effect = IntegrityError(
            "unsafe SQL", {}, original
        )
        repository = SQLAlchemyCartRepository(store)
        with pytest.raises(error) as caught:
            await (repository._flush() if operation == "flush" else repository.commit())
        assert (
            "SQL" not in caught.value.message and constraint not in caught.value.message
        )
        store.commit.assert_not_awaited() if operation == "flush" else None

    import asyncio

    asyncio.run(scenario())


def test_repository_rolls_back_only_when_application_requests():
    async def scenario():
        store = session()
        await SQLAlchemyCartRepository(store).rollback()
        store.rollback.assert_awaited_once()

    import asyncio

    asyncio.run(scenario())


def test_item_update_refuses_unowned_parent_without_writes():
    async def scenario():
        store = session()
        store.execute.return_value = result()
        cart = Cart(customer_id=uuid4(), branch_id=uuid4())
        item = CartItem(
            cart_id=uuid4(),
            product_id=uuid4(),
            presentation_id=uuid4(),
            quantity=1,
            notes=None,
            base_price_snapshot=Decimal("1"),
            presentation_price_snapshot=Decimal("1"),
            addons_price_snapshot=Decimal("0"),
            unit_price_snapshot=Decimal("1"),
        )
        with pytest.raises(CartItemNotFoundError):
            await SQLAlchemyCartRepository(store).update_item(cart, item)
        store.flush.assert_not_awaited()

    import asyncio

    asyncio.run(scenario())
