"""Opt-in TEST-only PostgreSQL migration, constraints and atomic checkout."""

import asyncio

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.infrastructure.authorization import (
    SQLAlchemyCatalogAuthorization,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.modules.orders.application.dtos import OrderCreate
from app.modules.orders.application.services import OrderService
from app.modules.orders.domain.models import OrderMode, PaymentMethodType, PaymentStatus
from app.modules.orders.infrastructure.authorization import SQLAlchemyOrderAuthorization
from app.modules.orders.infrastructure.cart import SQLAlchemyCartCheckoutGateway
from app.modules.orders.infrastructure.customers import (
    SQLAlchemyCustomerCheckoutGateway,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyOrderSettingsRepository,
)
from app.modules.orders.infrastructure.scheduling import SQLAlchemyKitchenLoadEstimator
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase3_postgresql import migrate_cart_and_check_constraints
from tests.test_phase1_migration import migration_config
from tests.test_phase4_migration import EXPECTED_PHASE_FOUR_TABLES

pytestmark = pytest.mark.integration


def migrate_orders_and_constraints(connection):
    ids = migrate_cart_and_check_constraints(connection)
    config = migration_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "0004_orders")
    tables = set(inspect(connection).get_table_names())
    assert EXPECTED_PHASE_FOUR_TABLES <= tables and len(tables) == 35
    assert (
        connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0004_orders"
    )
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM delivery_zones WHERE branch_id IS NULL "
                "AND is_free AND delivery_fee=0"
            )
        )
        == 3
    )
    assert (
        connection.scalar(
            text("SELECT count(*) FROM delivery_zones WHERE district='tARaPoTo'")
        )
        == 1
    )
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM permissions WHERE code IN "
                "('ORDER_MANAGE','ORDER_SETTINGS_MANAGE')"
            )
        )
        == 2
    )
    assert (
        connection.scalar(
            text("""
        SELECT count(*) FROM role_permissions rp
        JOIN roles r ON r.id=rp.role_id JOIN permissions p ON p.id=rp.permission_id
        WHERE r.code='ADMIN' AND p.code IN ('ORDER_MANAGE','ORDER_SETTINGS_MANAGE')
    """)
        )
        == 2
    )
    insert_order = """
        INSERT INTO orders(source_cart_id,customer_id,branch_id,mode,status,
        payment_method_type,payment_status,subtotal,charges_total,discount_total,
        delivery_fee,total,customer_name_snapshot,customer_phone_snapshot,
        idempotency_key,request_fingerprint,branch_settings_snapshot)
        VALUES (:cart,:customer,:branch,'LOCAL','PENDING_CASH_CONFIRMATION',
        'CASH','PENDING',20,0,0,0,20,'Test','+51900000111',
        'constraints-test',repeat('a',64),'{}'::jsonb)
    """
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(insert_order), ids)
        cases = [
            (insert_order, "23505"),
            ("UPDATE orders SET total=21", "23514"),
            ("UPDATE orders SET subtotal=-1,total=-1", "23514"),
            ("UPDATE orders SET subtotal='NaN',total='NaN'", "23514"),
            ("UPDATE orders SET delivery_fee=-1", "23514"),
            ("UPDATE orders SET mode='BAD'", "23514"),
            ("UPDATE orders SET status='BAD'", "23514"),
            ("UPDATE orders SET mode='DELIVERY',payment_method_type='CASH'", "23514"),
            (
                "UPDATE orders SET customer_id='00000000-0000-0000-0000-000000000000'",
                "23503",
            ),
            (insert_order.replace("'constraints-test'", "'different-key'"), "23505"),
        ]
        for statement, state in cases:
            with pytest.raises(IntegrityError) as caught:
                with connection.begin_nested():
                    connection.execute(text(statement), ids)
            assert getattr(caught.value.orig, "sqlstate", None) == state
        for table in (
            "orders",
            "restaurant_tables",
            "branch_order_settings",
            "delivery_zones",
        ):
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_trigger t JOIN pg_class c "
                        "ON c.oid=t.tgrelid WHERE c.relname=:table "
                        "AND NOT t.tgisinternal AND t.tgname=:trigger"
                    ),
                    {"table": table, "trigger": "trg_" + table + "_set_updated_at"},
                )
                == 1
            )
        qr_token = connection.scalar(
            text(
                "INSERT INTO restaurant_tables(branch_id,label) "
                "VALUES (:branch,'Constraint table') RETURNING qr_token"
            ),
            ids,
        )
        with pytest.raises(IntegrityError) as caught:
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO restaurant_tables(branch_id,label,qr_token) "
                        "VALUES (:branch,'Duplicate QR',:qr)"
                    ),
                    {**ids, "qr": qr_token},
                )
        assert getattr(caught.value.orig, "sqlstate", None) == "23505"
        assert inspect(connection).get_columns("orders")[1]["identity"]["start"] == 1
    finally:
        savepoint.rollback()
    return ids


class FailingCheckout(SQLAlchemyCartCheckoutGateway):
    async def mark_checked_out(self, cart):
        await super().mark_checked_out(cart)
        raise RuntimeError("Simulated failure just before final commit")


def test_phase4_migration_constraints_checkout_rollback_and_downgrade_in_test_only(
    request,
):
    url = guarded_test_url(request)

    async def verify():
        engine = create_async_engine(url, echo=False, connect_args={"timeout": 5})
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
                    ids = await connection.run_sync(migrate_orders_and_constraints)
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        repository = SQLAlchemyOrderRepository(session)
                        catalog = CatalogService(
                            SQLAlchemyCatalogRepository(session),
                            SQLAlchemyCatalogAuthorization(session),
                            SQLAlchemyAuditRecorder(session),
                        )
                        settings = SQLAlchemyOrderSettingsRepository(session)
                        authorization = SQLAlchemyOrderAuthorization(session)
                        customers = SQLAlchemyCustomerCheckoutGateway(session)
                        estimator = SQLAlchemyKitchenLoadEstimator(repository)
                        table = (
                            await session.execute(
                                text(
                                    "INSERT INTO restaurant_tables(branch_id,label) "
                                    "VALUES (:branch,'Mesa TEST') RETURNING qr_token"
                                ),
                                ids,
                            )
                        ).scalar_one()
                        await session.commit()
                        guest = Principal(
                            principal_type=PrincipalType.GUEST,
                            customer_id=ids["customer"],
                        )
                        command_body = OrderCreate(
                            mode=OrderMode.LOCAL,
                            table_qr_token=table,
                            payment_method=PaymentMethodType.CASH,
                        )
                        failing = OrderService(
                            repository,
                            FailingCheckout(session, catalog),
                            customers,
                            settings,
                            estimator,
                            authorization,
                        )
                        with pytest.raises(RuntimeError):
                            await failing.create(guest, "rollback-test", command_body)
                        for name in (
                            "orders",
                            "order_items",
                            "order_item_addon_options",
                            "order_status_history",
                            "order_local_details",
                        ):
                            assert (
                                await session.scalar(
                                    text(f"SELECT count(*) FROM {name}")
                                )
                                == 0
                            )
                        assert (
                            await session.scalar(
                                text("SELECT status FROM carts WHERE id=:cart"), ids
                            )
                            == "ACTIVE"
                        )
                        service = OrderService(
                            repository,
                            SQLAlchemyCartCheckoutGateway(session, catalog),
                            customers,
                            settings,
                            estimator,
                            authorization,
                        )
                        order = await service.create(guest, "live-test", command_body)
                        assert (
                            order.order_number > 0
                            and order.total
                            == (
                                await repository.get_owned(ids["customer"], order.id)
                            ).total
                        )
                        assert (
                            await session.scalar(
                                text("SELECT status FROM carts WHERE id=:cart"), ids
                            )
                            == "CHECKED_OUT"
                        )
                        assert (
                            await service.create(guest, "live-test", command_body)
                        ).id == order.id
                        assert (
                            await repository.get_owned(ids["other_customer"], order.id)
                            is None
                        )
                        admin = Principal(
                            principal_type=PrincipalType.REGISTERED,
                            user_id=ids["actor"],
                        )
                        released = await service.confirm_cash_release(admin, order.id)
                        assert released.payment_status == PaymentStatus.PENDING
                        assert len(released.history) == 2
                        assert (
                            await session.scalar(
                                text("SELECT count(*) FROM order_status_history")
                            )
                            == 2
                        )
                        await session.rollback()

                    def downgrade_test(sync):
                        config = migration_config()
                        config.attributes["connection"] = sync
                        # An explicit TEST savepoint verifies safe refusal while
                        # leaving every historical row intact.
                        with pytest.raises(DBAPIError):
                            with sync.begin_nested():
                                command.downgrade(config, "0003_cart")
                        assert sync.scalar(text("SELECT count(*) FROM orders")) == 1
                        # Recover the checkpoint before Phase 4 checkout in TEST
                        # rather than rewrite CHECKED_OUT carts in any real DB.

                    await connection.run_sync(downgrade_test)
                finally:
                    await outer.rollback()
                assert (
                    await connection.run_sync(
                        lambda sync: inspect(sync).get_table_names()
                    )
                    == []
                )

                # Separate empty TEST transaction validates the actual down DDL.
                await connection.rollback()  # End the read-only inspection autobegin.
                outer = await connection.begin()
                try:
                    await connection.run_sync(migrate_orders_and_constraints)

                    def clean_downgrade(sync):
                        config = migration_config()
                        config.attributes["connection"] = sync
                        command.downgrade(config, "0003_cart")
                        assert not EXPECTED_PHASE_FOUR_TABLES & set(
                            inspect(sync).get_table_names()
                        )
                        assert (
                            "products" in inspect(sync).get_table_names()
                            and "carts" in inspect(sync).get_table_names()
                        )
                        assert (
                            sync.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0003_cart"
                        )

                    await connection.run_sync(clean_downgrade)
                finally:
                    await outer.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
