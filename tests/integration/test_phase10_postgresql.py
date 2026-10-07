"""Opt-in dedicated EMPTY TEST database only; never touch the normal database."""

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.admin.application.services import AdministrationReadService
from app.modules.admin.domain.periods import branch_period
from app.modules.admin.infrastructure.read_repository import (
    SQLAlchemyAdministrationReadRepository,
    dashboard_statement,
)
from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.auth.infrastructure.persistence.repositories import (
    SQLAlchemyAuthRepository,
)
from app.modules.branches.application.admin_services import BranchAdministrationService
from app.modules.branches.application.services import (
    BranchService,
    UpdateStaffAssignment,
)
from app.modules.branches.infrastructure.order_timezone import (
    SQLAlchemyBranchTimezoneSynchronization,
)
from app.modules.branches.infrastructure.persistence.admin_repository import (
    SQLAlchemyBranchAdministrationRepository,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.customers.application.admin_services import (
    CustomerAdministrationService,
)
from app.modules.customers.infrastructure.persistence.admin_repository import (
    SQLAlchemyCustomerAdministrationRepository,
)
from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.application.services import OrderSettingsService
from app.modules.orders.domain.models import OrderMode, StatusHistory
from app.modules.orders.infrastructure.authorization import SQLAlchemyOrderAuthorization
from app.modules.orders.infrastructure.branch_administration import (
    SQLAlchemyBranchOrderConfiguration,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyOrderSettingsRepository,
)
from app.shared.application.administration import AdministrationConflict
from app.shared.domain.time import utc_now
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase5_postgresql import insert_operational_fixtures
from tests.integration.test_phase9_postgresql import (
    require_empty,
    upgrade_notifications,
)
from tests.modules.admin.test_domain import branch_values
from tests.test_phase1_migration import migration_config

pytestmark = pytest.mark.integration


def upgrade_admin(sync):
    ids = upgrade_notifications(sync)
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "0010_admin")
    assert len(inspect(sync).get_table_names()) == 51
    assert sync.scalar(text("SELECT version_num FROM alembic_version")) == "0010_admin"
    return ids


@asynccontextmanager
async def isolated_database(url):
    schema = "phase10_test_" + uuid4().hex
    assert re.fullmatch(r"phase10_test_[a-f0-9]{32}", schema)
    engine = create_async_engine(
        url,
        echo=False,
        hide_parameters=True,
        connect_args={
            "timeout": 5,
            "server_settings": {
                "search_path": schema + ",public",
                "lock_timeout": "5s",
                "statement_timeout": "15s",
            },
        },
    )
    committed = False
    extensions = set()
    try:
        async with engine.begin() as connection:
            await require_empty(connection)
            preexisting = set(
                (
                    await connection.execute(text("SELECT extname FROM pg_extension"))
                ).scalars()
            )
            for name in ("citext", "pgcrypto"):
                await connection.execute(
                    text(
                        "CREATE EXTENSION IF NOT EXISTS " + name + " WITH SCHEMA public"
                    )
                )
                if name not in preexisting:
                    extensions.add(name)
            await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
            ids = await connection.run_sync(upgrade_admin)
        committed = True
        yield engine, ids
    finally:
        if committed:
            async with engine.begin() as cleanup:
                owner = await cleanup.scalar(
                    text(
                        "SELECT pg_get_userbyid(nspowner)=current_user FROM "
                        "pg_namespace WHERE nspname=:name"
                    ),
                    {"name": schema},
                )
                assert owner is True
                await cleanup.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
                for name in sorted(extensions):
                    assert name in {"citext", "pgcrypto"}
                    await cleanup.execute(text("DROP EXTENSION " + name))
                await require_empty(cleanup)
        await engine.dispose()


def actor(ids):
    return Principal(principal_type=PrincipalType.REGISTERED, user_id=ids["actor"])


def branch_service(session):
    return BranchAdministrationService(
        SQLAlchemyBranchRepository(session),
        SQLAlchemyBranchAdministrationRepository(session),
        SQLAlchemyBranchOrderConfiguration(session),
        SQLAlchemyAuditRecorder(session),
    )


def customer_service(session):
    return CustomerAdministrationService(
        SQLAlchemyBranchRepository(session),
        SQLAlchemyCustomerAdministrationRepository(session),
        SQLAlchemyAuditRecorder(session),
    )


def test_phase10_real_schema_scopes_identity_transactions_dashboard_and_downgrade(
    request,
):
    url = guarded_test_url(request)

    async def verify():
        async with isolated_database(url) as (engine, ids):
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                service = customer_service(session)
                guest = await service.mutate(
                    actor(ids),
                    ids["branch"],
                    "CREATE",
                    {"full_name": "TEST admin contact", "phone": "+519000001010"},
                )
                assert guest.is_guest and guest.phone_verified_at is None
                assert (
                    await session.scalar(
                        text("SELECT created_by_branch_id FROM customers WHERE id=:id"),
                        {"id": guest.id},
                    )
                    == ids["branch"]
                )
                await session.rollback()
                auth = SQLAlchemyAuthRepository(session)
                user = await auth.add_user(
                    email="phase10-customer@example.test",
                    phone=guest.phone,
                    password_hash="test-only-unused",
                    first_name="Verified",
                    last_name=None,
                    verified_at=utc_now(),
                )
                await auth.promote_customer(
                    guest.id,
                    user_id=user.id,
                    full_name="Verified",
                    email=user.email,
                    verified_at=utc_now(),
                )
                await session.commit()
                updated = await service.mutate(
                    actor(ids),
                    ids["branch"],
                    "UPDATE",
                    {
                        "first_name": "Coherent",
                        "last_name": "Identity",
                        "email": "coherent@example.test",
                    },
                    guest.id,
                )
                assert not updated.is_guest and updated.full_name == "Coherent Identity"
                assert (
                    await session.scalar(
                        text(
                            "SELECT first_name || ' ' || last_name FROM users "
                            "WHERE id=:id"
                        ),
                        {"id": user.id},
                    )
                    == updated.full_name
                )
                await session.rollback()
                with pytest.raises(AdministrationConflict) as exc:
                    await service.mutate(
                        actor(ids), ids["branch"], "DELETE", {}, guest.id
                    )
                assert exc.value.code == "REGISTERED_CUSTOMER_CANNOT_BE_DELETED"

                class FailingAudit:
                    async def record(self, event):
                        raise RuntimeError("TEST injected audit failure")

                failing = CustomerAdministrationService(
                    SQLAlchemyBranchRepository(session),
                    SQLAlchemyCustomerAdministrationRepository(session),
                    FailingAudit(),
                )
                with pytest.raises(RuntimeError):
                    await failing.mutate(
                        actor(ids),
                        ids["branch"],
                        "CREATE",
                        {"full_name": "Rollback", "phone": "+519000001011"},
                    )
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM customers WHERE phone='+519000001011'"
                        )
                    )
                    == 0
                )
                await session.rollback()
                branch = await branch_service(session).create(
                    actor(ids), branch_values()
                )
                assert len(branch["hours"]) == 7
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM branch_order_settings WHERE "
                            "branch_id=:id"
                        ),
                        {"id": branch["id"]},
                    )
                    == 1
                )
                await session.rollback()
                await branch_service(session).mutate(
                    actor(ids), branch["id"], "UPDATE", {"timezone": "Asia/Tokyo"}
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT timezone FROM branch_order_settings WHERE "
                            "branch_id=:id"
                        ),
                        {"id": branch["id"]},
                    )
                    == "Asia/Tokyo"
                )
                await session.rollback()
                await OrderSettingsService(
                    SQLAlchemyOrderSettingsRepository(session),
                    SQLAlchemyOrderAuthorization(session),
                    branch_timezones=SQLAlchemyBranchTimezoneSynchronization(session),
                    audit=SQLAlchemyAuditRecorder(session),
                ).update_settings(actor(ids), branch["id"], {"timezone": "UTC"})
                assert (
                    await session.scalar(
                        text("SELECT timezone FROM branches WHERE id=:id"),
                        {"id": branch["id"]},
                    )
                    == "UTC"
                )
                await session.rollback()
                await branch_service(session).mutate(
                    actor(ids), branch["id"], "DELETE", {}
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM staff_assignments WHERE branch_id=:id"
                        ),
                        {"id": branch["id"]},
                    )
                    == 1
                )
                await session.rollback()
                orders = await insert_operational_fixtures(session, ids)
                now = utc_now()
                local = next(o for o in orders if o.mode == OrderMode.LOCAL)
                old_at = now - timedelta(days=365)
                old_cart = await session.scalar(
                    text(
                        "INSERT INTO carts(customer_id,branch_id,status) "
                        "VALUES (:customer,:branch,'CHECKED_OUT') RETURNING id"
                    ),
                    ids,
                )
                old_order = replace(
                    local,
                    id=uuid4(),
                    order_number=None,
                    source_cart_id=old_cart,
                    idempotency_key="phase10-old-paid-order",
                    items=tuple(
                        replace(
                            i,
                            id=uuid4(),
                            created_at=old_at,
                            addon_options=tuple(
                                replace(a, id=uuid4()) for a in i.addon_options
                            ),
                        )
                        for i in local.items
                    ),
                    history=(
                        StatusHistory(
                            from_status=None,
                            to_status=local.status,
                            created_at=old_at,
                        ),
                    ),
                    created_at=old_at,
                    updated_at=old_at,
                    confirmed_at=old_at,
                )
                await SQLAlchemyOrderRepository(session).create(old_order)
                for order in [o for o in orders if o.id != local.id] + [old_order]:
                    paid = old_at if order.id == old_order.id else now
                    await session.execute(
                        text(
                            "INSERT INTO payments(order_id,method_type,amount,"
                            "status,paid_at) VALUES (:id,:method,:amount,'PAID',"
                            ":paid)"
                        ),
                        {
                            "id": order.id,
                            "method": order.payment_method_type.value,
                            "amount": order.total,
                            "paid": paid,
                        },
                    )
                payment = await session.scalar(
                    text("SELECT id FROM payments WHERE order_id=:id"),
                    {"id": old_order.id},
                )
                await session.execute(
                    text(
                        "UPDATE orders SET status='CANCELLED',"
                        "payment_status='PAID' WHERE id=:id"
                    ),
                    {"id": old_order.id},
                )
                await session.execute(
                    text(
                        "INSERT INTO refunds(payment_id,order_id,amount,"
                        "method_type,status,requested_at,refunded_at) VALUES "
                        "(:payment,:order,:amount,'CASH','REFUNDED',:requested,"
                        ":refunded)"
                    ),
                    {
                        "payment": payment,
                        "order": old_order.id,
                        "amount": old_order.total,
                        "requested": now - timedelta(days=1),
                        "refunded": now,
                    },
                )
                await session.execute(
                    text(
                        "UPDATE products SET name='Renamed current catalog' "
                        "WHERE id=:id"
                    ),
                    {"id": ids["product"]},
                )
                await session.commit()
                first, last = (now - timedelta(days=2)).date(), now.date()
                read = AdministrationReadService(
                    SQLAlchemyBranchRepository(session),
                    SQLAlchemyAdministrationReadRepository(session),
                )
                report = await read.dashboard(
                    actor(ids),
                    now=now,
                    branch_id=ids["branch"],
                    from_date=first,
                    to_date=last,
                )
                assert report["summary"]["gross_sales"] == Decimal("94.00")
                assert report["summary"]["refunded_amount"] == Decimal("47.00")
                assert report["summary"]["net_sales"] == Decimal("47.00")
                assert report["summary"]["orders_count"] == 3
                assert report["summary"]["paid_orders_count"] == 2
                assert report["top_products"] == [
                    {
                        "product_id": ids["product"],
                        "product_name": "Aeropuerto original",
                        "quantity": 4,
                    }
                ]
                local_metric = next(
                    m for m in report["sales_by_mode"] if m["mode"] == "LOCAL"
                )
                assert local_metric["net_sales"] == Decimal("-47.00")
                p = branch_period(ids["branch"], "TEST", "UTC", now, first, last)
                stmt, params = dashboard_statement((p,))
                plan = await session.scalar(
                    text("EXPLAIN (FORMAT JSON) " + str(stmt)), params
                )
                assert plan[0]["Plan"]
                await session.rollback()
                with pytest.raises(AdministrationConflict) as busy:
                    await branch_service(session).mutate(
                        actor(ids), ids["branch"], "DELETE", {}
                    )
                assert busy.value.code == "BRANCH_HAS_ACTIVE_OPERATIONS"
            async with engine.begin() as connection:
                with pytest.raises(DBAPIError):
                    async with connection.begin_nested():

                        def downgrade(sync):
                            cfg = migration_config()
                            cfg.attributes["connection"] = sync
                            command.downgrade(cfg, "0009_notifications")

                        await connection.run_sync(downgrade)

    asyncio.run(verify())


async def race_order(session, ids, template, code):
    branch = await branch_service(session).create(
        actor(ids), branch_values() | {"code": code}
    )
    table = await session.scalar(
        text(
            "INSERT INTO restaurant_tables(branch_id,label) VALUES (:branch,"
            "'TEST race table') RETURNING id"
        ),
        {"branch": branch["id"]},
    )
    cart = await session.scalar(
        text(
            "INSERT INTO carts(customer_id,branch_id,status) VALUES (:customer,"
            ":branch,'CHECKED_OUT') RETURNING id"
        ),
        {"customer": ids["customer"], "branch": branch["id"]},
    )
    now = utc_now()
    order = replace(
        template,
        id=uuid4(),
        order_number=None,
        branch_id=branch["id"],
        source_cart_id=cart,
        idempotency_key=code,
        branch_settings_snapshot=replace(
            template.branch_settings_snapshot, branch_id=branch["id"]
        ),
        local_details=replace(template.local_details, restaurant_table_id=table),
        items=tuple(
            replace(
                i,
                id=uuid4(),
                addon_options=tuple(replace(a, id=uuid4()) for a in i.addon_options),
            )
            for i in template.items
        ),
        history=(
            StatusHistory(from_status=None, to_status=template.status, created_at=now),
        ),
        created_at=now,
        updated_at=now,
        confirmed_at=now,
    )
    await session.commit()
    return branch["id"], order


def test_phase10_real_two_connection_last_admin_and_branch_order_races(request):
    url = guarded_test_url(request)

    async def verify():
        async with isolated_database(url) as (engine, ids):
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as seed:
                orders = await insert_operational_fixtures(seed, ids)
                second = await seed.scalar(
                    text(
                        "INSERT INTO users(email,first_name,password_hash) "
                        "VALUES ('phase10-second-admin@example.test','Second',"
                        "'TEST unused') RETURNING id"
                    )
                )
                assignment_b = await seed.scalar(
                    text(
                        "INSERT INTO staff_assignments(user_id,branch_id,role_id,"
                        "employee_code) SELECT :user,:branch,id,'SECOND-ADMIN' "
                        "FROM roles WHERE code='ADMIN' AND scope='BRANCH' "
                        "RETURNING id"
                    ),
                    {"user": second, "branch": ids["branch"]},
                )
                assignment_a = await seed.scalar(
                    text(
                        "SELECT id FROM staff_assignments WHERE user_id=:actor "
                        "AND branch_id=:branch"
                    ),
                    ids,
                )
                await seed.commit()
            entered, release = asyncio.Event(), asyncio.Event()
            async with factory() as a, factory() as b:

                class HeldAudit:
                    async def record(self, event):
                        await SQLAlchemyAuditRecorder(a).record(event)
                        entered.set()
                        await asyncio.wait_for(release.wait(), 5)

                first = asyncio.create_task(
                    BranchService(
                        SQLAlchemyBranchRepository(a), HeldAudit()
                    ).update_staff(
                        actor(ids),
                        ids["branch"],
                        assignment_a,
                        UpdateStaffAssignment(is_active=False),
                    )
                )
                await asyncio.wait_for(entered.wait(), 5)
                second_actor = Principal(
                    principal_type=PrincipalType.REGISTERED, user_id=second
                )
                task = asyncio.create_task(
                    BranchService(
                        SQLAlchemyBranchRepository(b), SQLAlchemyAuditRecorder(b)
                    ).update_staff(
                        second_actor,
                        ids["branch"],
                        assignment_b,
                        UpdateStaffAssignment(is_active=False),
                    )
                )
                try:
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), 0.15)
                    release.set()
                    await asyncio.wait_for(first, 5)
                    with pytest.raises(AdministrationConflict) as last:
                        await asyncio.wait_for(task, 5)
                    assert last.value.code == "LAST_BRANCH_ADMIN"
                finally:
                    release.set()
                    for pending in (first, task):
                        if not pending.done():
                            pending.cancel()
                    await asyncio.gather(first, task, return_exceptions=True)
                # Restore A via remaining B, so subsequent branch tests retain
                # their actor.
                await BranchService(
                    SQLAlchemyBranchRepository(b), SQLAlchemyAuditRecorder(b)
                ).update_staff(
                    second_actor,
                    ids["branch"],
                    assignment_a,
                    UpdateStaffAssignment(is_active=True),
                )
            template = next(o for o in orders if o.mode == OrderMode.LOCAL)
            async with factory() as seed:
                branch, order = await race_order(
                    seed, ids, template, "DEACTIVATE-FIRST"
                )
            async with factory() as a, factory() as b:
                assert await SQLAlchemyBranchRepository(a).lock_branch(branch)
                await SQLAlchemyBranchAdministrationRepository(a).deactivate_branch(
                    branch
                )

                async def insert():
                    try:
                        await SQLAlchemyOrderRepository(b).create(order)
                        await b.commit()
                    finally:
                        await b.rollback()

                task = asyncio.create_task(insert())
                try:
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), 0.15)
                    await a.commit()
                    with pytest.raises(OrderConflictError):
                        await asyncio.wait_for(task, 5)
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                assert (
                    await b.scalar(
                        text("SELECT count(*) FROM orders WHERE id=:id"),
                        {"id": order.id},
                    )
                    == 0
                )
            async with factory() as seed:
                branch, order = await race_order(seed, ids, template, "ORDER-FIRST")
            async with factory() as a, factory() as b:
                await SQLAlchemyOrderRepository(a).create(order)
                task = asyncio.create_task(
                    branch_service(b).mutate(actor(ids), branch, "DELETE", {})
                )
                try:
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), 0.15)
                    await a.commit()
                    with pytest.raises(AdministrationConflict) as busy:
                        await asyncio.wait_for(task, 5)
                    assert busy.value.code == "BRANCH_HAS_ACTIVE_OPERATIONS"
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await a.rollback()
                    await b.rollback()
                assert (
                    await b.scalar(
                        text("SELECT is_active FROM branches WHERE id=:id"),
                        {"id": branch},
                    )
                    is True
                )

    asyncio.run(verify())
