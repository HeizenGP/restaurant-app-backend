"""Opt-in TEST-only fulfillment integration; caller rolls back all DDL/data.

This verifies database constraints and transactional operations, not genuine
multi-connection race scheduling. Unit race tests and SQL lock assertions are
separate; deployment must validate real contention before enabling a worker.
"""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.fulfillment.application.errors import FulfillmentPermissionDeniedError
from app.modules.fulfillment.application.services import FulfillmentService
from app.modules.fulfillment.domain.models import DecisionStatus
from app.modules.fulfillment.infrastructure.authorization import (
    SQLAlchemyFulfillmentAuthorization,
)
from app.modules.fulfillment.infrastructure.orders import (
    SQLAlchemyFulfillmentOrdersGateway,
)
from app.modules.fulfillment.infrastructure.persistence.repositories import (
    SQLAlchemyFulfillmentRepository,
)
from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.application.services import KitchenService
from app.modules.kitchen.infrastructure.authorization import (
    SQLAlchemyKitchenAuthorization,
)
from app.modules.kitchen.infrastructure.orders import SQLAlchemyKitchenOrdersGateway
from app.modules.orders.domain.models import OrderMode, OrderStatus
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
)
from app.shared.domain.time import utc_now
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase5_postgresql import insert_operational_fixtures
from tests.integration.test_phase6_postgresql import upgrade_payments
from tests.test_phase1_migration import migration_config
from tests.test_phase7_migration import FULFILLMENT_TABLES

pytestmark = pytest.mark.integration


def upgrade_fulfillment(sync):
    ids = upgrade_payments(sync)
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "0007_fulfillment")
    assert len(inspect(sync).get_table_names()) == 41
    assert (
        sync.scalar(text("SELECT version_num FROM alembic_version"))
        == "0007_fulfillment"
    )
    grants = set(
        sync.execute(
            text(
                "SELECT r.code,p.code FROM role_permissions rp "
                "JOIN roles r ON r.id=rp.role_id "
                "JOIN permissions p ON p.id=rp.permission_id "
                "WHERE p.code IN ('FULFILLMENT_VIEW','FULFILLMENT_MANAGE',"
                "'DELIVERY_ASSIGN','DELIVERY_DELAY_REVIEW')"
            )
        ).all()
    )
    assert grants == {
        ("ADMIN", code)
        for code in (
            "FULFILLMENT_VIEW",
            "FULFILLMENT_MANAGE",
            "DELIVERY_ASSIGN",
            "DELIVERY_DELAY_REVIEW",
        )
    }
    return ids


class FailingHistoryGateway(SQLAlchemyFulfillmentOrdersGateway):
    def __init__(self, session):
        super().__init__(session)
        self.test_session = session

    async def transition(self, order, history):
        await super().transition(order, history)
        await self.test_session.execute(
            text(
                "INSERT INTO order_status_history(order_id,to_status) "
                "VALUES (:missing,'WAITING')"
            ),
            {"missing": uuid4()},
        )


class FailingCloseRepository(SQLAlchemyFulfillmentRepository):
    async def close_assignment(self, original, updated):
        if updated.completed_at:
            await self.session.execute(
                text(
                    "INSERT INTO order_status_history(order_id,to_status) "
                    "VALUES (:missing,'DELIVERED')"
                ),
                {"missing": uuid4()},
            )
        return await super().close_assignment(original, updated)


def service(
    session,
    now,
    *,
    gateway=SQLAlchemyFulfillmentOrdersGateway,
    repository=SQLAlchemyFulfillmentRepository,
):
    return FulfillmentService(
        repository(session),
        gateway(session),
        SQLAlchemyFulfillmentAuthorization(session),
        SQLAlchemyAuditRecorder(session),
        clock=lambda: now,
    )


def test_fulfillment_schema_transitions_constraints_rollback_and_downgrade(request):
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
                            "AND n.nspname NOT IN "
                            "('pg_catalog','information_schema') "
                            "AND n.nspname NOT LIKE 'pg_toast%'"
                        )
                    )
                    if objects.first() is not None:
                        pytest.fail(
                            "Integration requires an empty dedicated TEST database",
                            pytrace=False,
                        )
                    ids = await connection.run_sync(upgrade_fulfillment)
                    boundary = await connection.begin_nested()
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        records = await insert_operational_fixtures(session, ids)
                        pickup = next(o for o in records if o.mode == OrderMode.PICKUP)
                        delivery = next(
                            o for o in records if o.mode == OrderMode.DELIVERY
                        )
                        admin = Principal(
                            principal_type=PrincipalType.REGISTERED,
                            user_id=ids["actor"],
                        )
                        cook = Principal(
                            principal_type=PrincipalType.REGISTERED, user_id=ids["cook"]
                        )
                        # TEST-only scheduled status; retain original schedule.
                        await session.execute(
                            text("UPDATE orders SET status='SCHEDULED' WHERE id=:id"),
                            {"id": pickup.id},
                        )
                        await session.execute(
                            text(
                                "UPDATE order_status_history "
                                "SET to_status='SCHEDULED' WHERE order_id=:id"
                            ),
                            {"id": pickup.id},
                        )
                        await session.commit()
                        now = utc_now() + timedelta(hours=1)
                        fulfillment = service(session, now)
                        with pytest.raises(FulfillmentPermissionDeniedError):
                            await fulfillment.release_pickup(
                                cook, ids["branch"], pickup.id
                            )
                        with pytest.raises(IntegrityError):
                            await service(
                                session, now, gateway=FailingHistoryGateway
                            ).release_pickup(admin, ids["branch"], pickup.id)
                        assert (
                            await session.scalar(
                                text("SELECT status FROM orders WHERE id=:id"),
                                {"id": pickup.id},
                            )
                            == "SCHEDULED"
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM order_status_history "
                                    "WHERE order_id=:id AND to_status='WAITING'"
                                ),
                                {"id": pickup.id},
                            )
                            == 0
                        )
                        await session.rollback()
                        released = await fulfillment.release_due_pickups(
                            admin, ids["branch"], 10
                        )
                        assert released.released == 1
                        assert not (
                            await fulfillment.release_pickup(
                                admin, ids["branch"], pickup.id
                            )
                        ).changed
                        kitchen = KitchenService(
                            SQLAlchemyKitchenOrdersGateway(session),
                            SQLAlchemyKitchenAuthorization(session),
                            clock=lambda: now,
                        )
                        assert pickup.id in {
                            o.id
                            for o in (
                                await kitchen.get_queue(
                                    cook, ids["branch"], KitchenQueueQuery()
                                )
                            ).waiting
                        }
                        await session.rollback()
                        await kitchen.start_preparation(cook, ids["branch"], pickup.id)
                        await kitchen.mark_ready(cook, ids["branch"], pickup.id)
                        assert (
                            await fulfillment.complete_pickup(
                                admin,
                                ids["branch"],
                                pickup.id,
                                "TEST only",
                                "+51900000111",
                            )
                        ).status == OrderStatus.PICKED_UP
                        await kitchen.start_preparation(
                            cook, ids["branch"], delivery.id
                        )
                        await kitchen.mark_ready(cook, ids["branch"], delivery.id)
                        assignment = await fulfillment.assign_delivery(
                            admin, ids["branch"], delivery.id, ids["cook"]
                        )
                        assert (
                            await fulfillment.assign_delivery(
                                admin, ids["branch"], delivery.id, ids["cook"]
                            )
                        ).id == assignment.id
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(
                                    text(
                                        "INSERT INTO delivery_assignments"
                                        "(order_id,assigned_user_id,"
                                        "assigned_by_user_id,assigned_at) "
                                        "VALUES (:order,:cook,:actor,:now)"
                                    ),
                                    {**ids, "order": delivery.id, "now": now},
                                )
                        await session.rollback()
                        await fulfillment.dispatch_delivery(
                            admin, ids["branch"], delivery.id
                        )
                        with pytest.raises(IntegrityError):
                            await service(
                                session, now, repository=FailingCloseRepository
                            ).complete_delivery(admin, ids["branch"], delivery.id)
                        assert (
                            await session.scalar(
                                text("SELECT status FROM orders WHERE id=:id"),
                                {"id": delivery.id},
                            )
                            == "OUT_FOR_DELIVERY"
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT completed_at "
                                    "FROM delivery_assignments WHERE id=:id"
                                ),
                                {"id": assignment.id},
                            )
                            is None
                        )
                        await session.rollback()
                        assert (
                            await fulfillment.complete_delivery(
                                admin, ids["branch"], delivery.id
                            )
                        ).changed
                        assert not (
                            await fulfillment.complete_delivery(
                                admin, ids["branch"], delivery.id
                            )
                        ).changed
                        assert (
                            await fulfillment.detect_delivery_delays(
                                admin, ids["branch"]
                            )
                        ).new_incidents == 1
                        incident = (
                            await fulfillment.list_delays(admin, ids["branch"])
                        )[0]
                        await session.rollback()
                        assert (
                            await service(
                                session, now + timedelta(days=10)
                            ).detect_delivery_delays(admin, ids["branch"])
                        ).existing_incidents == 1
                        assert (await fulfillment.list_delays(admin, ids["branch"]))[
                            0
                        ] == incident
                        await session.rollback()
                        decided = await fulfillment.decide_delay(
                            admin,
                            ids["branch"],
                            incident.id,
                            DecisionStatus.APPROVED,
                            False,
                            "Verified manually",
                            "Manual follow-up, no refund",
                        )
                        assert decided.decision_status == DecisionStatus.APPROVED
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(
                                    text(
                                        "UPDATE delivery_delay_incidents "
                                        "SET delay_seconds_at_detection=900"
                                    )
                                )
                        await session.rollback()
                        for original in (pickup, delivery):
                            historical = await SQLAlchemyOrderRepository(
                                session
                            ).get_owned(ids["customer"], original.id)
                            assert (
                                historical.total == original.total
                                and historical.items == original.items
                            )
                            if original.mode == OrderMode.PICKUP:
                                assert (
                                    historical.pickup_details == original.pickup_details
                                )
                            else:
                                assert (
                                    historical.delivery_details
                                    == original.delivery_details
                                )
                        await session.rollback()

                    def refuse_downgrade(sync):
                        config = migration_config()
                        config.attributes["connection"] = sync
                        with pytest.raises(DBAPIError):
                            with sync.begin_nested():
                                command.downgrade(config, "0006_payments")
                        assert (
                            sync.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0007_fulfillment"
                        )
                        assert FULFILLMENT_TABLES <= set(
                            inspect(sync).get_table_names()
                        )

                    await connection.run_sync(refuse_downgrade)
                    await boundary.rollback()

                    def empty_downgrade(sync):
                        count = sync.scalar(text("SELECT count(*) FROM carts"))
                        config = migration_config()
                        config.attributes["connection"] = sync
                        command.downgrade(config, "0006_payments")
                        assert not FULFILLMENT_TABLES & set(
                            inspect(sync).get_table_names()
                        )
                        assert len(inspect(sync).get_table_names()) == 39
                        assert sync.scalar(text("SELECT count(*) FROM carts")) == count
                        command.upgrade(config, "0007_fulfillment")
                        assert len(inspect(sync).get_table_names()) == 41

                    await connection.run_sync(empty_downgrade)
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
