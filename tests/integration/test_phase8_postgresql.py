"""Opt-in dedicated empty TEST PostgreSQL; all DDL/data rolled back.
Single connection validates real constraints/atomicity, not multi-connection races.
No production schema detection disables the mandatory Phase 8 late-payment hook.
"""

import asyncio
from dataclasses import asdict, replace

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cancellations.domain.models import ReasonCode, RequestStatus
from app.modules.cancellations.presentation.dependencies import get_cancellation_service
from app.modules.fulfillment.infrastructure.persistence.models import (
    DeliveryAssignmentModel,
)
from app.modules.orders.domain.models import OrderMode
from app.modules.payments.application.services import PaymentService
from app.modules.payments.domain.refunds import RefundStatus
from app.modules.payments.infrastructure.authorization import (
    SQLAlchemyPaymentAuthorization,
)
from app.modules.payments.infrastructure.orders import SQLAlchemyPaymentOrderLifecycle
from app.modules.payments.infrastructure.persistence.repositories import (
    SQLAlchemyPaymentRepository,
)
from app.modules.payments.presentation.refund_dependencies import get_refund_service
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase5_postgresql import insert_operational_fixtures
from tests.integration.test_phase6_postgresql import SessionAwareTestGateway
from tests.integration.test_phase7_postgresql import upgrade_fulfillment
from tests.modules.fulfillment.test_domain import assignment
from tests.modules.payments.fakes import signed_event
from tests.test_phase1_migration import migration_config
from tests.test_phase8_migration import PHASE8_TABLES

pytestmark = pytest.mark.integration


def upgrade_cancellations(sync):
    ids = upgrade_fulfillment(sync)
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "0008_cancellations_refunds")
    assert len(inspect(sync).get_table_names()) == 47
    assert (
        sync.scalar(text("SELECT version_num FROM alembic_version"))
        == "0008_cancellations_refunds"
    )
    grants = set(
        sync.execute(
            text(
                "SELECT r.code,p.code FROM role_permissions rp JOIN roles r ON "
                "r.id=rp.role_id JOIN permissions p ON p.id=rp.permission_id WHERE "
                "p.code IN "
                "('CANCELLATION_VIEW','CANCELLATION_MANAGE','REFUND_MANAGE')"
            )
        ).all()
    )
    assert grants == {
        ("ADMIN", code)
        for code in ("CANCELLATION_VIEW", "CANCELLATION_MANAGE", "REFUND_MANAGE")
    }
    return ids


class FailingRegistration:
    def __init__(self, real):
        self.real = real

    async def register_if_paid(self, order, now):
        await self.real.register_if_paid(order, now)
        raise RuntimeError("Injected failure after full refund/history INSERT")


def test_phase8_real_schema_obligation_late_capture_rollback_and_safe_downgrade(
    request,
):
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
                            "ON n.oid=c.relnamespace WHERE c.relkind IN "
                            "('r','p','v','m','f','S') AND n.nspname NOT IN "
                            "('pg_catalog','information_schema') AND n.nspname NOT "
                            "LIKE 'pg_toast%'"
                        )
                    )
                    if objects.first() is not None:
                        pytest.fail(
                            "Integration requires an empty dedicated TEST database",
                            pytrace=False,
                        )
                    ids = await connection.run_sync(upgrade_cancellations)
                    ledger = await connection.begin_nested()
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        records = await insert_operational_fixtures(session, ids)
                        local = next(o for o in records if o.mode == OrderMode.LOCAL)
                        pickup = next(o for o in records if o.mode == OrderMode.PICKUP)
                        delivery = next(
                            o for o in records if o.mode == OrderMode.DELIVERY
                        )
                        admin = Principal(
                            principal_type=PrincipalType.REGISTERED,
                            user_id=ids["actor"],
                        )
                        owner = Principal(
                            principal_type=PrincipalType.GUEST,
                            customer_id=ids["customer"],
                        )
                        # TEST-only initialization of online fixture before capture.
                        await session.execute(
                            text(
                                "UPDATE orders SET "
                                "status='PENDING_PAYMENT',"
                                "payment_status='PENDING',confirmed_at=NULL "
                                "WHERE id=:id"
                            ),
                            {"id": pickup.id},
                        )
                        await session.commit()
                        payment_gateway = SessionAwareTestGateway(session)
                        payment_service = PaymentService(
                            SQLAlchemyPaymentRepository(session),
                            SQLAlchemyPaymentOrderLifecycle(session),
                            SQLAlchemyPaymentAuthorization(session),
                            payment_gateway,
                        )
                        paid = await payment_service.confirm_cash(
                            admin, ids["branch"], local.id
                        )
                        cancellation = get_cancellation_service(session)
                        request_result = await cancellation.create_request(
                            owner, local.id, "TEST change of plans"
                        )
                        rid = request_result.request.id
                        # Actual unique partial request constraint.
                        with pytest.raises(DBAPIError):
                            async with session.begin_nested():
                                await session.execute(
                                    text(
                                        "INSERT INTO "
                                        "cancellation_requests(order_id,"
                                        "customer_id,branch_id,reason,requested_at) "
                                        "VALUES (:order,:customer,:branch,"
                                        "'Different request',now())"
                                    ),
                                    {**ids, "order": local.id},
                                )
                        await session.rollback()
                        # A late failure rolls back Order/history/cancellation/refund
                        # together.
                        real = cancellation.refunds
                        cancellation.refunds = FailingRegistration(real)
                        with pytest.raises(RuntimeError):
                            await cancellation.review(
                                admin, ids["branch"], rid, RequestStatus.APPROVED
                            )
                        assert (
                            await session.scalar(
                                text("SELECT status FROM orders WHERE id=:id"),
                                {"id": local.id},
                            )
                            == "WAITING"
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT status FROM cancellation_requests "
                                    "WHERE id=:id"
                                ),
                                {"id": rid},
                            )
                            == "PENDING"
                        )
                        assert (
                            await session.scalar(text("SELECT count(*) FROM refunds"))
                            == 0
                        )
                        await session.rollback()
                        cancellation.refunds = real
                        outcome = await cancellation.review(
                            admin, ids["branch"], rid, RequestStatus.APPROVED
                        )
                        assert outcome.refund.amount == local.total
                        refunds = get_refund_service(session, None)
                        returned = await refunds.confirm_cash(
                            admin, ids["branch"], outcome.refund.id
                        )
                        assert returned.status == RefundStatus.REFUNDED
                        assert (
                            await session.scalar(
                                text("SELECT status FROM payments WHERE id=:id"),
                                {"id": paid.payment.id},
                            )
                            == "PAID"
                        )
                        # Force deferred checks; an outer rollback alone would not run
                        # them.
                        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                        await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                        await session.commit()
                        bad_sql = [
                            (
                                "UPDATE refunds SET amount=amount-1 WHERE id=:id",
                                {"id": returned.id},
                            ),
                            (
                                "UPDATE refunds SET order_id=:other WHERE id=:id",
                                {"id": returned.id, "other": delivery.id},
                            ),
                            (
                                "UPDATE order_cancellations SET "
                                "reason_text='rewrite' WHERE order_id=:id",
                                {"id": local.id},
                            ),
                            (
                                "DELETE FROM refund_status_history WHERE refund_id=:id",
                                {"id": returned.id},
                            ),
                            (
                                "UPDATE orders SET status='WAITING' WHERE id=:id",
                                {"id": local.id},
                            ),
                            (
                                "UPDATE payments SET status='FAILED',paid_at=NULL "
                                "WHERE id=:id",
                                {"id": paid.payment.id},
                            ),
                            (
                                "UPDATE orders SET status='CANCELLED' WHERE id=:id",
                                {"id": delivery.id},
                            ),
                        ]
                        for sql, parameters in bad_sql:
                            with pytest.raises(DBAPIError):
                                async with session.begin_nested():
                                    await session.execute(text(sql), parameters)
                                    await session.execute(
                                        text("SET CONSTRAINTS ALL IMMEDIATE")
                                    )
                        await session.rollback()
                        # Production Payment repository, mandatory real 0008 hook.
                        initiated = await payment_service.initiate_online(
                            owner, pickup.id, "phase8-original-payment"
                        )
                        unpaid = await cancellation.cancel_order(
                            admin, ids["branch"], pickup.id, ReasonCode.OUT_OF_STOCK
                        )
                        assert unpaid.refund is None
                        body, headers = signed_event(
                            initiated.attempt,
                            event="phase8-late-capture",
                            amount=str(pickup.total),
                            occurred_at=utc_now(),
                        )
                        await payment_service.webhook("test_gateway", body, headers)
                        await payment_service.webhook("test_gateway", body, headers)
                        assert (
                            await session.scalar(
                                text("SELECT status FROM orders WHERE id=:id"),
                                {"id": pickup.id},
                            )
                            == "CANCELLED"
                        )
                        assert (
                            await session.scalar(
                                text("SELECT payment_status FROM orders WHERE id=:id"),
                                {"id": pickup.id},
                            )
                            == "PAID"
                        )
                        assert (
                            await session.scalar(
                                text("SELECT count(*) FROM refunds WHERE order_id=:id"),
                                {"id": pickup.id},
                            )
                            == 1
                        )
                        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                        await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                        await session.commit()
                        # Paid delivery with active assignment is closed, not deleted.
                        await session.execute(
                            text(
                                "INSERT INTO "
                                "payments(order_id,amount,method_type,"
                                "status,paid_at) VALUES (:id,:amount,"
                                "'ONLINE','PAID',now())"
                            ),
                            {"id": delivery.id, "amount": delivery.total},
                        )
                        a = replace(
                            assignment(),
                            order_id=delivery.id,
                            assigned_user_id=ids["actor"],
                            assigned_by_user_id=ids["actor"],
                            assigned_at=utc_now(),
                            created_at=utc_now(),
                        )
                        session.add(DeliveryAssignmentModel(**asdict(a)))
                        await session.commit()
                        await cancellation.cancel_order(
                            admin, ids["branch"], delivery.id, ReasonCode.OUT_OF_STOCK
                        )
                        assert await session.scalar(
                            text(
                                "SELECT unassigned_at IS NOT NULL FROM "
                                "delivery_assignments WHERE id=:id"
                            ),
                            {"id": a.id},
                        )
                        await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                        await session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                        await session.commit()
                    # Downgrade is forbidden with any financial/decision history.
                    guard = await connection.begin_nested()
                    try:

                        def blocked(sync):
                            config = migration_config()
                            config.attributes["connection"] = sync
                            command.downgrade(config, "0007_fulfillment")

                        with pytest.raises(DBAPIError):
                            await connection.run_sync(blocked)
                    finally:
                        await guard.rollback()
                    assert PHASE8_TABLES <= await connection.run_sync(
                        lambda sync: set(inspect(sync).get_table_names())
                    )
                    await ledger.rollback()

                    def empty_downgrade(sync):
                        config = migration_config()
                        config.attributes["connection"] = sync
                        command.downgrade(config, "0007_fulfillment")
                        assert len(inspect(sync).get_table_names()) == 41

                    await connection.run_sync(empty_downgrade)
                finally:
                    await outer.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
