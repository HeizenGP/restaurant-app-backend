"""Opt-in, isolated TEST-only Kitchen DDL, permissions and atomic operations."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.application.errors import KitchenPermissionDeniedError
from app.modules.kitchen.application.services import KitchenService
from app.modules.kitchen.infrastructure.authorization import (
    SQLAlchemyKitchenAuthorization,
)
from app.modules.kitchen.infrastructure.orders import SQLAlchemyKitchenOrdersGateway
from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    DeliveryDetails,
    LocalDetails,
    Order,
    OrderAddonOption,
    OrderItem,
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    PickupDetails,
    StatusHistory,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
)
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase4_postgresql import migrate_orders_and_constraints
from tests.test_phase1_migration import migration_config
from tests.test_phase5_migration import PHASE_FIVE_INDEXES

pytestmark = pytest.mark.integration


def upgrade_kitchen(sync):
    ids = migrate_orders_and_constraints(sync)
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "0005_kitchen")
    assert (
        sync.scalar(text("SELECT version_num FROM alembic_version")) == "0005_kitchen"
    )
    assert len(inspect(sync).get_table_names()) == 35
    grants = set(
        sync.execute(
            text("""
        SELECT r.code, p.code FROM role_permissions rp
        JOIN roles r ON r.id=rp.role_id JOIN permissions p ON p.id=rp.permission_id
        WHERE p.code IN ('KITCHEN_VIEW','KITCHEN_MANAGE')
    """)
        ).all()
    )
    assert grants == {
        ("ADMIN", "KITCHEN_VIEW"),
        ("ADMIN", "KITCHEN_MANAGE"),
        ("KITCHEN", "KITCHEN_VIEW"),
        ("KITCHEN", "KITCHEN_MANAGE"),
    }
    assert (
        sync.scalar(
            text("""
        SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id=rp.role_id
        JOIN permissions p ON p.id=rp.permission_id WHERE r.code='KITCHEN'
        AND p.code IN ('ORDER_MANAGE','ORDER_SETTINGS_MANAGE')
    """)
        )
        == 0
    )
    indexes = {
        index["name"]
        for table in ("orders", "order_status_history")
        for index in inspect(sync).get_indexes(table)
    }
    assert PHASE_FIVE_INDEXES <= indexes
    return ids


async def insert_operational_fixtures(session, ids):
    """Fixtures already confirmed; not a payment/scheduling implementation."""
    now = utc_now()
    waiting_at = now - timedelta(minutes=20)
    table_id = await session.scalar(
        text(
            "INSERT INTO restaurant_tables(branch_id,label) "
            "VALUES (:branch,'Mesa TEST') RETURNING id"
        ),
        ids,
    )
    zone = await session.scalar(
        text(
            "SELECT id FROM delivery_zones WHERE district='Tarapoto' "
            "AND branch_id IS NULL"
        )
    )
    orders = []
    for index, mode in enumerate(OrderMode):
        cart = ids["cart"] if index == 0 else uuid4()
        if index != 0:
            await session.execute(
                text(
                    "INSERT INTO carts(id,customer_id,branch_id,status) "
                    "VALUES (:id,:customer,:branch,'CHECKED_OUT')"
                ),
                {**ids, "id": cart},
            )
        local = pickup = delivery = None
        method = (
            PaymentMethodType.CASH
            if mode == OrderMode.LOCAL
            else PaymentMethodType.ONLINE
        )
        paid = (
            PaymentStatus.PENDING
            if method == PaymentMethodType.CASH
            else PaymentStatus.PAID
        )
        if mode == OrderMode.LOCAL:
            local = LocalDetails(
                restaurant_table_id=table_id,
                table_label_snapshot="Mesa TEST",
                payment_choice=method,
                cash_confirmation_required_snapshot=True,
            )
        elif mode == OrderMode.PICKUP:
            pickup = PickupDetails(
                requested_pickup_at=now + timedelta(minutes=15),
                calculated_kitchen_release_at=waiting_at,
                estimated_ready_at=now + timedelta(minutes=10),
                pickup_name_snapshot="TEST only",
                pickup_phone_snapshot="+51900000111",
            )
        else:
            delivery = DeliveryDetails(
                customer_address_id=None,
                delivery_zone_id=zone,
                delivery_zone_name_snapshot="Tarapoto",
                recipient_name_snapshot="TEST only",
                recipient_phone_snapshot="+51900000111",
                address_line_snapshot="Private TEST address",
                reference_text_snapshot=None,
                district_snapshot="Tarapoto",
                city_snapshot="Tarapoto",
                department_snapshot="San Martín",
                latitude_snapshot=None,
                longitude_snapshot=None,
                delivery_fee_snapshot=Decimal("0.00"),
                estimated_delivery_at=now + timedelta(minutes=40),
            )
        order = Order(
            source_cart_id=cart,
            customer_id=ids["customer"],
            branch_id=ids["branch"],
            mode=mode,
            status=OrderStatus.WAITING,
            payment_method_type=method,
            payment_status=paid,
            customer_name_snapshot="Private TEST name",
            customer_phone_snapshot="+51900000111",
            idempotency_key="kitchen-test-" + mode.value,
            request_fingerprint="a" * 64,
            subtotal=Decimal("47.00"),
            charges_total=Decimal("0.00"),
            discount_total=Decimal("0.00"),
            delivery_fee=Decimal("0.00"),
            total=Decimal("47.00"),
            items=(
                OrderItem(
                    product_id=ids["product"],
                    presentation_id=ids["presentation"],
                    product_name_snapshot="Aeropuerto original",
                    presentation_name_snapshot="Plato original",
                    quantity=2,
                    notes="Sin cebolla",
                    base_price_snapshot=Decimal("20.00"),
                    presentation_price_snapshot=Decimal("20.00"),
                    addons_price_snapshot=Decimal("3.50"),
                    unit_price_snapshot=Decimal("23.50"),
                    line_total_snapshot=Decimal("47.00"),
                    addon_options=(
                        OrderAddonOption(
                            product_addon_id=ids["addon"],
                            product_addon_option_id=ids["option"],
                            addon_name_snapshot="Extras original",
                            option_name_snapshot="Extra original",
                            additional_price_snapshot=Decimal("3.50"),
                        ),
                    ),
                ),
            ),
            branch_settings_snapshot=BranchOrderSettings(branch_id=ids["branch"]),
            local_details=local,
            pickup_details=pickup,
            delivery_details=delivery,
            history=(
                StatusHistory(
                    from_status=None,
                    to_status=OrderStatus.WAITING,
                    created_at=waiting_at,
                ),
            ),
            created_at=waiting_at - timedelta(hours=1),
            updated_at=waiting_at,
            confirmed_at=waiting_at,
        )
        orders.append(await SQLAlchemyOrderRepository(session).create(order))
    # All these writes are TEST fixtures inside the caller-owned rollback.
    await session.execute(
        text("UPDATE carts SET status='CHECKED_OUT' WHERE id=:cart"), ids
    )
    ids["cook"] = uuid4()
    await session.execute(
        text(
            "INSERT INTO users(id,email,password_hash,first_name) "
            "VALUES (:cook,'kitchen-test@example.test','test-only-unused','Cook')"
        ),
        ids,
    )
    await session.execute(
        text(
            "INSERT INTO staff_assignments(user_id,branch_id,role_id,employee_code) "
            "SELECT :cook,:branch,id,'TEST-KITCHEN' FROM roles WHERE code='KITCHEN'"
        ),
        ids,
    )
    await session.commit()
    return orders


class FailingHistoryGateway(SQLAlchemyKitchenOrdersGateway):
    async def record_preparation_transition(self, order, history):
        # Real FK failure on the history INSERT AFTER the conditional status UPDATE.
        await super().record_preparation_transition(
            order, replace(history, changed_by_user_id=uuid4())
        )


def test_kitchen_upgrade_transitions_rollback_permissions_and_scoped_downgrade(request):
    url = guarded_test_url(request)

    async def verify():
        engine = create_async_engine(
            url, echo=False, hide_parameters=True, connect_args={"timeout": 5}
        )
        try:
            async with engine.connect() as connection:
                outer = await connection.begin()
                try:
                    objects = await connection.execute(
                        text(
                            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                            "ON n.oid=c.relnamespace "
                            "WHERE c.relkind IN ('r','p','v','m','f','S') "
                            "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                            "AND n.nspname NOT LIKE 'pg_toast%'"
                        )
                    )
                    if objects.first() is not None:
                        pytest.fail(
                            "Integration requires an empty dedicated TEST database",
                            pytrace=False,
                        )
                    ids = await connection.run_sync(upgrade_kitchen)
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        orders = await insert_operational_fixtures(session, ids)
                        actor = Principal(
                            principal_type=PrincipalType.REGISTERED, user_id=ids["cook"]
                        )
                        authorization = SQLAlchemyKitchenAuthorization(session)
                        gateway = SQLAlchemyKitchenOrdersGateway(session)
                        service = KitchenService(gateway, authorization)
                        queue = await service.get_queue(
                            actor, ids["branch"], KitchenQueueQuery()
                        )
                        assert len(queue.waiting) == 3 and not queue.preparing
                        assert {card.mode for card in queue.waiting} == set(OrderMode)
                        assert all(
                            card.timing.waiting_seconds >= 1200
                            for card in queue.waiting
                        )
                        await session.rollback()
                        failing = KitchenService(
                            FailingHistoryGateway(session), authorization
                        )
                        with pytest.raises(OrderConflictError):
                            await failing.start_preparation(
                                actor, ids["branch"], orders[0].id
                            )
                        assert (
                            await session.scalar(
                                text("SELECT status FROM orders WHERE id=:id"),
                                {"id": orders[0].id},
                            )
                            == "WAITING"
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM order_status_history "
                                    "WHERE order_id=:id"
                                ),
                                {"id": orders[0].id},
                            )
                            == 1
                        )
                        await session.rollback()
                        await session.execute(
                            text(
                                "UPDATE products SET name='Renamed',deleted_at=now() "
                                "WHERE id=:product"
                            ),
                            ids,
                        )
                        await session.commit()
                        for order in orders:
                            started = await service.start_preparation(
                                actor, ids["branch"], order.id
                            )
                            assert started.status == OrderStatus.PREPARING
                            assert (
                                started.items[0].product_name_snapshot
                                == "Aeropuerto original"
                            )
                            repeated = await service.start_preparation(
                                actor, ids["branch"], order.id
                            )
                            assert len(repeated.history) == 2
                            ready = await service.mark_ready(
                                actor, ids["branch"], order.id
                            )
                            target = (
                                OrderStatus.READY_FOR_PICKUP
                                if order.mode == OrderMode.PICKUP
                                else OrderStatus.READY
                            )
                            assert ready.status == target and len(ready.history) == 3
                            assert (
                                len(
                                    (
                                        await service.mark_ready(
                                            actor, ids["branch"], order.id
                                        )
                                    ).history
                                )
                                == 3
                            )
                            row = (
                                await session.execute(
                                    text(
                                        "SELECT status,payment_status,confirmed_at "
                                        "FROM orders WHERE id=:id"
                                    ),
                                    {"id": order.id},
                                )
                            ).one()
                            assert row.status == target.value
                            assert row.payment_status == order.payment_status.value
                            assert row.confirmed_at == order.confirmed_at
                            actors = (
                                (
                                    await session.execute(
                                        text(
                                            "SELECT changed_by_user_id "
                                            "FROM order_status_history "
                                            "WHERE order_id=:id "
                                            "AND from_status IS NOT NULL"
                                        ),
                                        {"id": order.id},
                                    )
                                )
                                .scalars()
                                .all()
                            )
                            assert actors == [actor.user_id, actor.user_id]
                        queue = await service.get_queue(
                            actor, ids["branch"], KitchenQueueQuery()
                        )
                        assert (
                            len(queue.ready) == 3
                            and not queue.waiting
                            and not queue.preparing
                        )
                        await session.execute(
                            text(
                                "UPDATE staff_assignments SET is_active=false "
                                "WHERE user_id=:cook"
                            ),
                            ids,
                        )
                        await session.commit()
                        with pytest.raises(KitchenPermissionDeniedError):
                            await service.get_queue(
                                actor, ids["branch"], KitchenQueueQuery()
                            )
                        await session.rollback()

                    def downgrade(sync):
                        counts = {
                            table: sync.scalar(text(f"SELECT count(*) FROM {table}"))
                            for table in (
                                "orders",
                                "order_items",
                                "order_status_history",
                                "carts",
                                "products",
                            )
                        }
                        config = migration_config()
                        config.attributes["connection"] = sync
                        command.downgrade(config, "0004_orders")
                        assert (
                            sync.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0004_orders"
                        )
                        assert all(
                            sync.scalar(text(f"SELECT count(*) FROM {table}")) == count
                            for table, count in counts.items()
                        )
                        assert (
                            sync.scalar(
                                text(
                                    "SELECT count(*) FROM permissions "
                                    "WHERE code IN ('KITCHEN_VIEW','KITCHEN_MANAGE')"
                                )
                            )
                            == 0
                        )
                        indexes = {
                            index["name"]
                            for table in ("orders", "order_status_history")
                            for index in inspect(sync).get_indexes(table)
                        }
                        assert not PHASE_FIVE_INDEXES & indexes
                        assert len(inspect(sync).get_table_names()) == 35

                    await connection.run_sync(downgrade)
                finally:
                    await outer.rollback()
                assert (
                    await connection.run_sync(
                        lambda sync: inspect(sync).get_table_names()
                    )
                    == []
                )
        finally:
            await engine.dispose()

    asyncio.run(verify())
