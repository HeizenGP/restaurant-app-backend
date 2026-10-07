"""Opt-in TEST-only PostgreSQL. Never use or reconcile the normal database.

Capture test rolls back all DDL/data. Concurrency test must commit across two
connections: creates a uniquely named schema in an EMPTY dedicated TEST database,
then removes only that schema and extensions installed by its own setup.
"""

import asyncio
import re
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.notifications.application.dtos import PushResult
from app.modules.notifications.application.errors import DeviceBusyError
from app.modules.notifications.application.push import PushDispatchService
from app.modules.notifications.domain.models import DevicePlatform, PushResultKind
from app.modules.notifications.infrastructure.persistence.push import (
    SQLAlchemyPushRepository,
)
from app.modules.notifications.infrastructure.persistence.repositories import (
    SQLAlchemyNotificationRepository,
)
from app.modules.notifications.infrastructure.push_gateway import (
    ConfiguredPushGatewayRegistry,
)
from app.modules.orders.domain.models import OrderMode, StatusHistory
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
)
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase5_postgresql import insert_operational_fixtures
from tests.integration.test_phase8_postgresql import upgrade_cancellations
from tests.modules.notifications.fakes import Clock, TestGateway
from tests.test_phase1_migration import migration_config
from tests.test_phase9_migration import PHASE9_TABLES

pytestmark = pytest.mark.integration


async def require_empty(connection):
    objects = await connection.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v','m','f','S') "
            "AND n.nspname NOT IN ('pg_catalog','information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%'"
        )
    )
    if objects.first() is not None:
        pytest.fail(
            "Phase 9 integration requires an empty dedicated TEST database",
            pytrace=False,
        )


def upgrade_notifications(sync):
    ids = upgrade_cancellations(sync)
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "0009_notifications")
    assert len(inspect(sync).get_table_names()) == 51
    assert sync.scalar(text("SELECT version_num FROM alembic_version")) == (
        "0009_notifications"
    )
    grants = sync.execute(
        text(
            "SELECT r.code,r.scope FROM role_permissions rp "
            "JOIN roles r ON r.id=rp.role_id "
            "JOIN permissions p ON p.id=rp.permission_id "
            "WHERE p.code='ORDER_REALTIME_VIEW'"
        )
    ).all()
    assert grants == [("ADMIN", "BRANCH")]
    assert all(
        sync.scalar(text("SELECT count(*) FROM " + table)) == 0
        for table in PHASE9_TABLES
    )  # Migration is not a historical backfill.
    return ids


async def transition(session, order, old, new, actor):
    now = utc_now()
    await session.execute(
        text("UPDATE orders SET status=:status WHERE id=:id"),
        {"status": new, "id": order.id},
    )
    await session.execute(
        text(
            "INSERT INTO order_status_history(order_id,from_status,to_status,"
            "changed_by_user_id,created_at) VALUES (:id,:old,:new,:actor,:now)"
        ),
        {"id": order.id, "old": old, "new": new, "actor": actor, "now": now},
    )


async def seed(session, ids):
    repo = SQLAlchemyNotificationRepository(session)
    d = await repo.register_device(
        ids["customer"],
        uuid4(),
        DevicePlatform.ANDROID,
        "test",
        "phase9-test-only-token",
        utc_now(),
    )
    await session.commit()
    records = await insert_operational_fixtures(session, ids)
    return d, records


def test_phase9_real_migration_capture_history_read_rollback_and_safe_downgrade(
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
                    await require_empty(connection)
                    ids = await connection.run_sync(upgrade_notifications)
                    ledger = await connection.begin_nested()
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        d, orders = await seed(session, ids)
                        local = next(o for o in orders if o.mode == OrderMode.LOCAL)
                        pickup = next(o for o in orders if o.mode == OrderMode.PICKUP)
                        delivery = next(
                            o for o in orders if o.mode == OrderMode.DELIVERY
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM customer_notifications "
                                    "WHERE kind='ORDER_RECEIVED'"
                                )
                            )
                            == 3
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM notification_push_deliveries"
                                )
                            )
                            == 3
                        )
                        repo = SQLAlchemyNotificationRepository(session)
                        baseline = await repo.high_watermark(branch=ids["branch"])
                        await session.rollback()
                        for order in orders:
                            await transition(
                                session, order, "WAITING", "PREPARING", ids["actor"]
                            )
                        await session.commit()
                        for order in (local, delivery):
                            await transition(
                                session, order, "PREPARING", "READY", ids["actor"]
                            )
                        await transition(
                            session,
                            pickup,
                            "PREPARING",
                            "READY_FOR_PICKUP",
                            ids["actor"],
                        )
                        await session.commit()
                        await transition(
                            session, delivery, "READY", "OUT_FOR_DELIVERY", ids["actor"]
                        )
                        await session.execute(
                            text(
                                "INSERT INTO delivery_delay_incidents("
                                "order_id,branch_id,"
                                "committed_eta,detected_at,observed_order_status,"
                                "delay_seconds_at_detection) VALUES "
                                "(:order,:branch,:eta,:now,'OUT_FOR_DELIVERY',1200)"
                            ),
                            {
                                "order": delivery.id,
                                "branch": ids["branch"],
                                "eta": utc_now() - timedelta(minutes=20),
                                "now": utc_now(),
                            },
                        )
                        await session.commit()
                        await transition(
                            session,
                            delivery,
                            "OUT_FOR_DELIVERY",
                            "DELIVERED",
                            ids["actor"],
                        )
                        await session.commit()
                        kinds = dict(
                            (
                                await session.execute(
                                    text(
                                        "SELECT kind,count(*) "
                                        "FROM customer_notifications "
                                        "GROUP BY kind"
                                    )
                                )
                            ).all()
                        )
                        assert kinds == {
                            "ORDER_RECEIVED": 3,
                            "ORDER_PREPARING": 3,
                            "ORDER_READY": 2,
                            "ORDER_READY_FOR_PICKUP": 1,
                            "ORDER_OUT_FOR_DELIVERY": 1,
                            "ORDER_DELIVERED": 1,
                            "DELIVERY_DELAYED": 1,
                        }
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM notification_push_deliveries"
                                )
                            )
                            == 12
                        )
                        event_count = await session.scalar(
                            text("SELECT count(*) FROM realtime_order_events")
                        )
                        n_count = sum(kinds.values())
                        # Rollback removes status, event, in-app and outbox together.
                        await transition(
                            session, local, "READY", "PREPARING", ids["actor"]
                        )
                        await session.rollback()
                        assert (
                            await session.scalar(
                                text("SELECT count(*) FROM realtime_order_events")
                            )
                            == event_count
                        )
                        assert (
                            await session.scalar(
                                text("SELECT count(*) FROM customer_notifications")
                            )
                            == n_count
                        )
                        assert (
                            await session.scalar(
                                text(
                                    "SELECT count(*) FROM notification_push_deliveries"
                                )
                            )
                            == n_count
                        )
                        owned = await repo.list_owned(ids["customer"], None, 50)
                        n = owned.items[0]
                        read = await repo.mark_read(ids["customer"], n.id, utc_now())
                        await session.commit()
                        assert (
                            await repo.mark_read(ids["customer"], n.id, utc_now())
                            == read
                        )
                        assert await repo.mark_read(uuid4(), n.id, utc_now()) is None
                        await session.rollback()
                        replay = await repo.events(ids["branch"], baseline, 100)
                        assert replay and all(e.id > baseline for e in replay)
                        await session.rollback()
                        for statement in (
                            "DELETE FROM realtime_order_events",
                            "UPDATE customer_notifications SET kind='ORDER_READY'",
                            "UPDATE customer_notifications SET read_at=NULL "
                            "WHERE read_at IS NOT NULL",
                        ):
                            with pytest.raises(DBAPIError):
                                async with session.begin_nested():
                                    await session.execute(text(statement))
                        await session.rollback()
                    config = migration_config()
                    config.attributes["connection"] = None
                    with pytest.raises(DBAPIError):
                        async with connection.begin_nested():

                            def downgrade(sync):
                                config.attributes["connection"] = sync
                                command.downgrade(config, "0008_cancellations_refunds")

                            await connection.run_sync(downgrade)
                    await ledger.rollback()
                    await connection.run_sync(downgrade)
                    assert (
                        len(
                            await connection.run_sync(
                                lambda sync: inspect(sync).get_table_names()
                            )
                        )
                        == 47
                    )
                finally:
                    await outer.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())


def test_phase9_real_two_connection_commit_cursor_skip_locked_and_privacy(request):
    url = guarded_test_url(request)

    async def verify():
        schema = "phase9_test_" + uuid4().hex
        assert re.fullmatch(r"phase9_test_[a-f0-9]{32}", schema)
        engine = create_async_engine(
            url,
            echo=False,
            hide_parameters=True,
            connect_args={
                "timeout": 5,
                "server_settings": {"search_path": schema + ",public"},
            },
        )
        committed = False
        new_extensions = set()
        try:
            async with engine.begin() as connection:
                await require_empty(connection)
                preexisting = set(
                    (
                        await connection.execute(
                            text("SELECT extname FROM pg_extension")
                        )
                    ).scalars()
                )
                for extension in ("citext", "pgcrypto"):
                    # Fixed names; install in public so isolated schema cleanup does
                    # not accidentally operate on extension members individually.
                    await connection.execute(
                        text(
                            "CREATE EXTENSION IF NOT EXISTS "
                            + extension
                            + " WITH SCHEMA public"
                        )
                    )
                    if extension not in preexisting:
                        new_extensions.add(extension)
                await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
                ids = await connection.run_sync(upgrade_notifications)
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    d, orders = await seed(session, ids)
            committed = True
            factory = async_sessionmaker(engine, expire_on_commit=False)
            local = next(o for o in orders if o.mode == OrderMode.LOCAL)
            pickup = next(o for o in orders if o.mode == OrderMode.PICKUP)
            async with factory() as a, factory() as b:
                assert await a.scalar(text("SELECT pg_backend_pid()")) != (
                    await b.scalar(text("SELECT pg_backend_pid()"))
                )
                await a.rollback()
                await b.rollback()
                watermark = await SQLAlchemyNotificationRepository(a).high_watermark(
                    branch=ids["branch"]
                )
                sequence = await SQLAlchemyNotificationRepository(a).high_watermark(
                    customer=ids["customer"]
                )
                await a.rollback()
                await transition(a, local, "WAITING", "PREPARING", ids["actor"])
                started = asyncio.Event()

                async def commit_second():
                    started.set()
                    await transition(b, pickup, "WAITING", "PREPARING", ids["actor"])
                    await b.commit()

                task = asyncio.create_task(commit_second())
                try:
                    await started.wait()
                    with pytest.raises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(task), timeout=0.15)
                    assert not task.done()  # B cannot publish a higher cursor first.
                    async with factory() as observer:
                        repo = SQLAlchemyNotificationRepository(observer)
                        assert (
                            await repo.high_watermark(branch=ids["branch"]) == watermark
                        )
                        assert (
                            await repo.high_watermark(customer=ids["customer"])
                            == sequence
                        )
                    await a.commit()
                    await asyncio.wait_for(task, timeout=5)
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await a.rollback()
                    await b.rollback()
            async with factory() as session:
                repo = SQLAlchemyNotificationRepository(session)
                events = await repo.events(ids["branch"], watermark, 100)
                notifications = await repo.stream_notifications(
                    ids["customer"],
                    sequence,
                    await repo.high_watermark(customer=ids["customer"]),
                    100,
                )
                assert [e.order_id for e in events] == [local.id, pickup.id]
                assert [n.order_id for n in notifications] == [local.id, pickup.id]
            clock = Clock(utc_now())
            first, second = (
                SQLAlchemyPushRepository(factory),
                SQLAlchemyPushRepository(factory),
            )
            groups = await asyncio.gather(
                first.claim(["test"], clock(), 1), second.claim(["test"], clock(), 1)
            )
            claims = [c for group in groups for c in group]
            assert len(claims) == 1  # One device lease, no duplicate live claim.
            old = claims[0]
            async with factory() as session:
                repo = SQLAlchemyNotificationRepository(session)
                foreign = await session.scalar(
                    text(
                        "INSERT INTO customers(full_name,phone,phone_verified_at) "
                        "VALUES ('Phase9 TEST foreign','+51900000999',now()) "
                        "RETURNING id"
                    )
                )
                await session.commit()
                with pytest.raises(DeviceBusyError):
                    await repo.register_device(
                        foreign,
                        d.installation_id,
                        d.platform,
                        d.provider_code,
                        "phase9-test-only-new-owner-token",
                        clock(),
                    )
                await session.rollback()
                await repo.unregister_device(d.customer_id, d.installation_id, clock())
                await session.commit()
                assert not await first.can_send(old, clock())
                clock.advance(121)
                rebound = await repo.register_device(
                    foreign,
                    d.installation_id,
                    d.platform,
                    d.provider_code,
                    "phase9-test-only-new-owner-token",
                    clock(),
                )
                await session.commit()
                assert rebound.generation > old.delivery.device_generation
            assert (
                await first.complete(
                    old, PushResult(kind=PushResultKind.INVALID_TOKEN), clock()
                )
                is None
            )
            async with factory() as session:
                assert (
                    await session.scalar(
                        text("SELECT is_active FROM notification_devices WHERE id=:id"),
                        {"id": d.id},
                    )
                    is True
                )
                # A real new Order INSERT generates the new owner's notification.
                cart = await session.scalar(
                    text(
                        "INSERT INTO carts(customer_id,branch_id,status) "
                        "VALUES (:customer,:branch,'CHECKED_OUT') RETURNING id"
                    ),
                    {"customer": foreign, "branch": ids["branch"]},
                )
                new_order = replace(
                    local,
                    id=uuid4(),
                    order_number=None,
                    customer_id=foreign,
                    source_cart_id=cart,
                    customer_name_snapshot="Phase9 TEST foreign",
                    customer_phone_snapshot="+51900000999",
                    idempotency_key="phase9-test-new-owner",
                    created_at=clock(),
                    updated_at=clock(),
                    confirmed_at=clock(),
                    items=tuple(
                        replace(
                            item,
                            id=uuid4(),
                            addon_options=tuple(
                                replace(option, id=uuid4())
                                for option in item.addon_options
                            ),
                        )
                        for item in local.items
                    ),
                    history=(
                        StatusHistory(
                            from_status=None, to_status=local.status, created_at=clock()
                        ),
                    ),
                )
                await SQLAlchemyOrderRepository(session).create(new_order)
                await session.commit()
            gateway = TestGateway()

            async def no_open_transaction(message):
                assert engine.sync_engine.pool.checkedout() == 0
                assert message.token == "phase9-test-only-new-owner-token"

            gateway.hook = no_open_transaction
            outcome = await PushDispatchService(
                first, ConfiguredPushGatewayRegistry([gateway]), clock=clock
            ).dispatch_pending_pushes()
            assert outcome.sent == 1 and len(gateway.messages) == 1
        finally:
            if committed:
                async with engine.begin() as cleanup:
                    owner = await cleanup.scalar(
                        text(
                            "SELECT pg_get_userbyid(nspowner)=current_user "
                            "FROM pg_namespace WHERE nspname=:name"
                        ),
                        {"name": schema},
                    )
                    assert owner is True
                    # Exact validated schema generated by this test only.
                    await cleanup.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
                    for extension in sorted(new_extensions):
                        assert extension in {"citext", "pgcrypto"}
                        await cleanup.execute(text("DROP EXTENSION " + extension))
                    await require_empty(cleanup)
            await engine.dispose()

    asyncio.run(verify())
