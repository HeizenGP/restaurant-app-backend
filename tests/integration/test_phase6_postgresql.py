"""Opt-in only: empty dedicated TEST database, all DDL/data rolled back."""

import asyncio
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.application.services import KitchenService
from app.modules.kitchen.infrastructure.authorization import (
    SQLAlchemyKitchenAuthorization,
)
from app.modules.kitchen.infrastructure.orders import SQLAlchemyKitchenOrdersGateway
from app.modules.orders.domain.models import OrderMode
from app.modules.payments.application.errors import PaymentCashPermissionDeniedError
from app.modules.payments.application.services import PaymentService
from app.modules.payments.domain.models import PaymentStatus
from app.modules.payments.infrastructure.authorization import (
    SQLAlchemyPaymentAuthorization,
)
from app.modules.payments.infrastructure.orders import SQLAlchemyPaymentOrderLifecycle
from app.modules.payments.infrastructure.persistence.repositories import (
    SQLAlchemyPaymentRepository,
)
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase5_postgresql import (
    insert_operational_fixtures,
    upgrade_kitchen,
)
from tests.modules.payments.fakes import MemoryDatabase, TestGateway, signed_event
from tests.test_phase1_migration import migration_config
from tests.test_phase6_migration import PAYMENT_TABLES

pytestmark = pytest.mark.integration


def upgrade_payments(sync):
    ids = upgrade_kitchen(sync)
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "0006_payments")
    assert len(inspect(sync).get_table_names()) == 39
    assert (
        sync.scalar(text("SELECT version_num FROM alembic_version")) == "0006_payments"
    )
    grants = set(
        sync.execute(
            text("""
        SELECT r.code,p.code FROM role_permissions rp
        JOIN roles r ON r.id=rp.role_id JOIN permissions p ON p.id=rp.permission_id
        WHERE p.code='PAYMENT_CASH_MANAGE'
    """)
        ).all()
    )
    assert grants == {("ADMIN", "PAYMENT_CASH_MANAGE")}
    assert PAYMENT_TABLES <= set(inspect(sync).get_table_names())
    return ids


class SessionAwareTestGateway(TestGateway):
    def __init__(self, session):
        super().__init__(MemoryDatabase())
        self.session = session

    async def create_payment_attempt(self, request):
        assert not self.session.in_transaction()
        return await super().create_payment_attempt(request)


class HistoricalPhase6PaymentRepository(SQLAlchemyPaymentRepository):
    """Characterizes the pinned 0006 schema, before refunds existed.

    Current production late-payment registration is tested against 0008 in
    test_phase8_postgresql, never disabled by production schema detection.
    """

    async def ensure_cancelled_refund(self, order, payment, now):
        pass


class FailingOrders(SQLAlchemyPaymentOrderLifecycle):
    def __init__(self, session):
        super().__init__(session)
        self.test_session = session

    async def confirm_paid(self, order, now, *, online):
        await super().confirm_paid(order, now, online=online)
        # Real FK violation AFTER Orders and Payment conditional writes.
        await self.test_session.execute(
            text(
                "INSERT INTO payment_status_history(payment_id,to_status,source) "
                "VALUES (:missing,'PENDING','SYSTEM')"
            ),
            {"missing": uuid4()},
        )


def test_payments_migration_constraints_atomicity_and_kitchen_projection(request):
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
                            "SELECT c.relname FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid=c.relnamespace "
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
                    ids = await connection.run_sync(upgrade_payments)
                    # Keep an independent empty-ledger savepoint to test safe downgrade.
                    ledger_boundary = await connection.begin_nested()
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        records = await insert_operational_fixtures(session, ids)
                        # TEST only: make historical fixtures unpaid BEFORE payments.
                        # This is not an application backfill.
                        await session.execute(
                            text(
                                "DELETE FROM order_status_history "
                                "WHERE order_id=ANY(:ids)"
                            ),
                            {"ids": [o.id for o in records]},
                        )
                        for order in records:
                            initial = (
                                "PENDING_CASH_CONFIRMATION"
                                if order.mode == OrderMode.LOCAL
                                else "PENDING_PAYMENT"
                            )
                            await session.execute(
                                text(
                                    "UPDATE orders SET status=:initial,"
                                    "payment_status='PENDING',confirmed_at=NULL "
                                    "WHERE id=:id"
                                ),
                                {"initial": initial, "id": order.id},
                            )
                            await session.execute(
                                text(
                                    "INSERT INTO order_status_history"
                                    "(order_id,to_status) "
                                    "VALUES (:id,:state)"
                                ),
                                {"id": order.id, "state": initial},
                            )
                        pickup = next(o for o in records if o.mode == OrderMode.PICKUP)
                        await session.execute(
                            text(
                                "UPDATE order_pickup_details "
                                "SET calculated_kitchen_release_at=:release "
                                "WHERE order_id=:id"
                            ),
                            {
                                "id": pickup.id,
                                # Use the fixture's own schedule: a fresh now()+10m
                                # can exceed estimated_ready_at by milliseconds.
                                "release": pickup.pickup_details.estimated_ready_at,
                            },
                        )
                        await session.commit()
                        admin = Principal(
                            principal_type=PrincipalType.REGISTERED,
                            user_id=ids["actor"],
                        )
                        cook = Principal(
                            principal_type=PrincipalType.REGISTERED, user_id=ids["cook"]
                        )
                        owner = Principal(
                            principal_type=PrincipalType.GUEST,
                            customer_id=ids["customer"],
                        )
                        repo = HistoricalPhase6PaymentRepository(session)
                        orders = SQLAlchemyPaymentOrderLifecycle(session)
                        authz = SQLAlchemyPaymentAuthorization(session)
                        gateway = SessionAwareTestGateway(session)
                        service = PaymentService(repo, orders, authz, gateway)
                        local = next(o for o in records if o.mode == OrderMode.LOCAL)
                        with pytest.raises(PaymentCashPermissionDeniedError):
                            await service.confirm_cash(cook, ids["branch"], local.id)
                        cash = await service.confirm_cash(
                            admin, ids["branch"], local.id
                        )
                        assert cash.payment.status == PaymentStatus.PAID
                        assert (
                            await service.confirm_cash(admin, ids["branch"], local.id)
                        ).payment.id == cash.payment.id
                        row = (
                            await session.execute(
                                text(
                                    "SELECT status,payment_status,confirmed_at "
                                    "FROM orders WHERE id=:id"
                                ),
                                {"id": local.id},
                            )
                        ).one()
                        assert tuple(row) == ("PENDING_CASH_CONFIRMATION", "PAID", None)
                        await session.rollback()
                        kitchen = KitchenService(
                            SQLAlchemyKitchenOrdersGateway(session),
                            SQLAlchemyKitchenAuthorization(session),
                        )
                        assert not (
                            await kitchen.get_queue(
                                cook, ids["branch"], KitchenQueueQuery()
                            )
                        ).waiting
                        await session.rollback()
                        for order in records:
                            if order.mode == OrderMode.LOCAL:
                                continue
                            result = await service.initiate_online(
                                owner, order.id, "postgres-test"
                            )
                            assert result.payment.payment.amount == order.total
                            body, headers = signed_event(
                                result.attempt,
                                amount=str(order.total),
                                event=str(order.id),
                            )
                            if order.mode == OrderMode.DELIVERY:
                                failing = PaymentService(
                                    repo, FailingOrders(session), authz, gateway
                                )
                                with pytest.raises(IntegrityError):
                                    await failing.webhook(
                                        gateway.provider_code, body, headers
                                    )
                                assert (
                                    await session.scalar(
                                        text(
                                            "SELECT status FROM payments "
                                            "WHERE order_id=:id"
                                        ),
                                        {"id": order.id},
                                    )
                                    == "PROCESSING"
                                )
                                assert (
                                    await session.scalar(
                                        text(
                                            "SELECT count(*) "
                                            "FROM payment_provider_events"
                                        )
                                    )
                                    == 1
                                )
                                await session.rollback()
                            await service.webhook(gateway.provider_code, body, headers)
                            await service.webhook(gateway.provider_code, body, headers)
                            current = await service.get(owner, order.id)
                            assert current.payment.status == PaymentStatus.PAID
                            expected = (
                                "SCHEDULED"
                                if order.mode == OrderMode.PICKUP
                                else "WAITING"
                            )
                            assert (
                                await session.scalar(
                                    text("SELECT status FROM orders WHERE id=:id"),
                                    {"id": order.id},
                                )
                                == expected
                            )
                            assert (
                                await session.scalar(
                                    text(
                                        "SELECT count(*) FROM payment_status_history "
                                        "WHERE payment_id=:id AND to_status='PAID'"
                                    ),
                                    {"id": current.payment.id},
                                )
                                == 1
                            )
                            await session.rollback()
                        queue = await kitchen.get_queue(
                            cook, ids["branch"], KitchenQueueQuery()
                        )
                        assert [o.mode for o in queue.waiting] == [OrderMode.DELIVERY]
                        await session.rollback()
                        # Database barriers, not merely in-memory assertions.
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(
                                    text(
                                        "INSERT INTO payments"
                                        "(order_id,method_type,amount) "
                                        "VALUES (:id,'CASH',47)"
                                    ),
                                    {"id": local.id},
                                )
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(
                                    text("UPDATE payments SET amount=-1")
                                )
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(
                                    text("UPDATE payments SET currency_code='USD'")
                                )
                        await session.rollback()

                    def refuse_downgrade(sync):
                        config = migration_config()
                        config.attributes["connection"] = sync
                        with pytest.raises(DBAPIError):
                            with sync.begin_nested():
                                command.downgrade(config, "0005_kitchen")
                        assert (
                            sync.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0006_payments"
                        )
                        assert PAYMENT_TABLES <= set(inspect(sync).get_table_names())

                    await connection.run_sync(refuse_downgrade)
                    await ledger_boundary.rollback()

                    def clean_downgrade(sync):
                        prior_count = sync.scalar(text("SELECT count(*) FROM carts"))
                        config = migration_config()
                        config.attributes["connection"] = sync
                        command.downgrade(config, "0005_kitchen")
                        assert not PAYMENT_TABLES & set(inspect(sync).get_table_names())
                        assert len(inspect(sync).get_table_names()) == 35
                        assert (
                            sync.scalar(text("SELECT count(*) FROM carts"))
                            == prior_count
                        )
                        assert (
                            sync.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0005_kitchen"
                        )
                        command.upgrade(config, "0006_payments")
                        assert len(inspect(sync).get_table_names()) == 39

                    await connection.run_sync(clean_downgrade)
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
