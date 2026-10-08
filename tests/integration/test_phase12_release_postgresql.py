"""Transversal release assertions in explicit EMPTY TEST PostgreSQL only."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.modules.auth.domain.models import OtpPurpose
from app.modules.auth.infrastructure.persistence.repositories import (
    SQLAlchemyAuthRepository,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.catalog.infrastructure.authorization import (
    SQLAlchemyCatalogAuthorization,
)
from app.modules.orders.application.errors import OrderNotFoundError
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.phase12_support import (
    checkout,
    fresh_database,
    owner,
    pay,
    seed,
    services,
    staff,
)

pytestmark = pytest.mark.integration


def test_real_otp_advisory_lock_serializes_empty_identity_and_releases_on_rollback(
    request,
):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            async with factory() as first, factory() as second:
                first_pid, second_pid = await asyncio.gather(
                    first.scalar(text("SELECT pg_backend_pid()")),
                    second.scalar(text("SELECT pg_backend_pid()")),
                )
                assert first_pid != second_pid
                phone = "+519000001299"
                purpose = OtpPurpose.GUEST_ACCESS
                assert (
                    await SQLAlchemyAuthRepository(first).latest_otp(
                        phone, purpose, lock=True
                    )
                    is None
                )
                waiter = asyncio.create_task(
                    SQLAlchemyAuthRepository(second).latest_otp(
                        phone, purpose, lock=True
                    )
                )
                try:
                    async with factory() as observer:

                        async def wait_until_blocked():
                            while not await observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_locks WHERE pid=:pid "
                                    "AND locktype='advisory' AND NOT granted"
                                ),
                                {"pid": second_pid},
                            ):
                                if waiter.done():
                                    # Propagate SQL errors, never mask them.
                                    await waiter
                                    pytest.fail("OTP contender did not wait")
                                await asyncio.sleep(0.01)

                        await asyncio.wait_for(wait_until_blocked(), 3)
                        assert not waiter.done()
                        # A different identity must not share this lock.
                        assert (
                            await SQLAlchemyAuthRepository(observer).latest_otp(
                                "+519000001298", purpose, lock=True
                            )
                            is None
                        )
                        await observer.rollback()
                        await first.rollback()
                        assert await asyncio.wait_for(waiter, 3) is None
                        assert (
                            await observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_locks WHERE pid=:pid "
                                    "AND locktype='advisory' AND granted"
                                ),
                                {"pid": second_pid},
                            )
                            == 1
                        )
                        await second.rollback()
                        assert (
                            await observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_locks WHERE "
                                    "pid IN (:first,:second) AND locktype='advisory'"
                                ),
                                {"first": first_pid, "second": second_pid},
                            )
                            == 0
                        )
                finally:
                    if not waiter.done():
                        waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
                    await first.rollback()
                    await second.rollback()

    asyncio.run(scenario())


def test_fresh_chain_to_head_committed_schema_persistence_and_rollback(request):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (engine, factory):
            ids = await seed(factory)
            async with factory() as session:
                order = await checkout(session, ids)
                await pay(session, ids, order)
                s = services(session)
                await s["kitchen"].start_preparation(
                    staff(ids, "cook"), ids["branch"], order.id
                )
                await s["kitchen"].mark_ready(
                    staff(ids, "cook"), ids["branch"], order.id
                )
                before = await session.scalar(
                    text("SELECT count(*) FROM realtime_order_events")
                )
                await session.rollback()
                s["orders"]._audit = AsyncMock()
                s["orders"]._audit.record.side_effect = RuntimeError(
                    "TEST audit failure"
                )
                with pytest.raises(RuntimeError):
                    await s["orders"].complete_local(
                        staff(ids), ids["branch"], order.id
                    )
            # Dispose every idle pooled connection, then read from a fresh pool.
            await engine.dispose()
            async with factory() as session:
                result = await services(session)["orders"].get(owner(ids), order.id)
                assert result.status == "READY" and result.payment_status == "PAID"
                assert result.history[-1].to_status == "READY"
                assert (
                    await session.scalar(
                        text("SELECT count(*) FROM realtime_order_events")
                    )
                    == before
                )
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM audit_logs "
                            "WHERE action='ORDER_LOCAL_SERVED'"
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "0011_customer_extras"
                )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "revocation",
    [
        "staff",
        "permission",
        "branch",
        "expired_assignment",
        "future_assignment",
        "inactive_user",
    ],
)
def test_multi_branch_permissions_revalidated_in_real_database(request, revocation):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            ids = await seed(factory)
            async with factory() as session:
                authorization = SQLAlchemyBranchRepository(session)
                assert await SQLAlchemyCatalogAuthorization(session).can_manage(
                    ids["admin"], None
                )
                for admin, branch, foreign in (
                    ("admin", "branch", "branch_b"),
                    ("admin_b", "branch_b", "branch"),
                ):
                    assert await authorization.has_permission(
                        ids[admin], ids[branch], "ORDER_MANAGE"
                    )
                    assert not await authorization.has_permission(
                        ids[admin], ids[foreign], "ORDER_MANAGE"
                    )
                assert await authorization.has_permission(
                    ids["cook"], ids["branch"], "KITCHEN_VIEW"
                )
                assert not await authorization.has_permission(
                    ids["cook"], ids["branch_b"], "KITCHEN_VIEW"
                )
                assert not await authorization.has_permission(
                    ids["cook"], ids["branch"], "ORDER_MANAGE"
                )
                await session.rollback()
            statements = {
                "staff": (
                    "UPDATE staff_assignments SET is_active=false WHERE user_id=:admin"
                ),
                "permission": (
                    "DELETE FROM role_permissions WHERE role_id="
                    "(SELECT id FROM roles WHERE code='ADMIN') AND permission_id="
                    "(SELECT id FROM permissions WHERE code='ORDER_MANAGE')"
                ),
                "branch": "UPDATE branches SET is_active=false WHERE id=:branch",
                "expired_assignment": (
                    "UPDATE staff_assignments SET ended_at=now() WHERE user_id=:admin"
                ),
                "future_assignment": (
                    "UPDATE staff_assignments SET assigned_at=:future "
                    "WHERE user_id=:admin"
                ),
                "inactive_user": (
                    "UPDATE users SET account_status='DISABLED' WHERE id=:admin"
                ),
            }
            async with factory() as writer:
                await writer.execute(
                    text(statements[revocation]),
                    {**ids, "future": utc_now() + timedelta(days=1)},
                )
                await writer.commit()
            async with factory() as reader:
                assert not await SQLAlchemyBranchRepository(reader).has_permission(
                    ids["admin"], ids["branch"], "ORDER_MANAGE"
                )
                if revocation != "permission":
                    assert not await SQLAlchemyCatalogAuthorization(reader).can_manage(
                        ids["admin"], None
                    )

    asyncio.run(scenario())


def test_customer_and_branch_idor_predicates_on_real_rows(request):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (_, factory):
            ids = await seed(factory)
            async with factory() as session:
                order = await checkout(session, ids)
                with pytest.raises(OrderNotFoundError):
                    await services(session)["orders"].get(
                        owner(ids, foreign=True), order.id
                    )
                await session.rollback()
                with pytest.raises(OrderNotFoundError):
                    await services(session)["orders"].complete_local(
                        staff(ids, "admin_b"), ids["branch_b"], order.id
                    )
                assert (
                    await session.scalar(
                        text("SELECT status FROM orders WHERE id=:id"), {"id": order.id}
                    )
                    == "PENDING_CASH_CONFIRMATION"
                )

    asyncio.run(scenario())
