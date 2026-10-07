"""Opt-in dedicated EMPTY test database; genuine separate-session races.

Never falls back to the normal database. Phase 10's guarded schema harness
migrates 1..10 before 0011 and removes only its validated, caller-owned schema.
Fiscal provider results below are TEST doubles, not legal issuance evidence.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.branches.infrastructure.customer_operations import (
    SQLAlchemyCustomerBranchReader,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.modules.favorites.infrastructure.persistence.repositories import (
    SQLAlchemyFavoriteRepository,
)
from app.modules.orders.infrastructure.customer_records import (
    SQLAlchemyCustomerOrderReader,
)
from app.modules.promotions.application.services import PromotionService
from app.modules.promotions.infrastructure.catalog import CatalogPrizeGateway
from app.modules.promotions.infrastructure.persistence.repositories import (
    SQLAlchemyPromotionRepository,
)
from app.modules.receipts.application.errors import FiscalProviderUnavailable
from app.modules.receipts.application.ports import FiscalResult
from app.modules.receipts.application.services import ReceiptService
from app.modules.receipts.infrastructure.fiscal_gateway import (
    UnconfiguredFiscalDocumentGateway,
)
from app.modules.receipts.infrastructure.persistence.repositories import (
    SQLAlchemyFiscalDocumentRepository,
)
from app.modules.reviews.application.services import ReviewService
from app.modules.reviews.infrastructure.persistence.repositories import (
    SQLAlchemyReviewRepository,
)
from app.shared.application.exceptions import ConflictError, ForbiddenError
from app.shared.domain.time import utc_now
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase5_postgresql import insert_operational_fixtures
from tests.integration.test_phase10_postgresql import isolated_database
from tests.modules.extras_support import Random
from tests.test_phase1_migration import migration_config
from tests.test_phase11_migration import PERMISSIONS, TABLES

pytestmark = pytest.mark.integration


def migration(sync, target, *, downgrade=False):
    config = migration_config()
    config.attributes["connection"] = sync
    (command.downgrade if downgrade else command.upgrade)(config, target)


@asynccontextmanager
async def database(url):
    async with isolated_database(url) as (engine, ids):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda sync: migration(sync, "0011_customer_extras")
            )
            assert (
                len(
                    await connection.run_sync(
                        lambda sync: inspect(sync).get_table_names()
                    )
                )
                == 60
            )
        yield engine, ids, async_sessionmaker(engine, expire_on_commit=False)


def owner(ids):
    return Principal(principal_type=PrincipalType.GUEST, customer_id=ids["customer"])


def admin(ids):
    return Principal(principal_type=PrincipalType.REGISTERED, user_id=ids["actor"])


def promotion_service(session, repository=None, random=None, now=None):
    return PromotionService(
        repository or SQLAlchemyPromotionRepository(session),
        SQLAlchemyCustomerBranchReader(session),
        SQLAlchemyBranchRepository(session),
        CatalogPrizeGateway(
            CatalogService(SQLAlchemyCatalogRepository(session), None, None)
        ),
        SQLAlchemyAuditRecorder(session),
        random or Random(),
        clock=lambda: now or utc_now(),
    )


async def campaign_fixture(factory, ids, *, cooldown=0, max_awards=None):
    now = utc_now()
    async with factory() as session:
        service = promotion_service(session, now=now)
        campaign = await service.create_campaign(
            admin(ids),
            ids["branch"],
            {
                "name": "TEST Free Campaign",
                "terms_text": "Free. No purchase or payment.",
                "starts_at": now,
                "spin_cooldown_seconds": cooldown,
                "reward_validity_days": 2,
            },
        )
        prize = await service.change_prize(
            admin(ids),
            ids["branch"],
            campaign.id,
            {
                "product_id": ids["product"],
                "display_name": "TEST Prize",
                "probability_bps": 1000,
                "max_awards": max_awards,
            },
        )
        await service.change_campaign(
            admin(ids), ids["branch"], campaign.id, {"is_active": True}
        )
    return campaign, prize, now


async def operational_fixture(factory, ids):
    async with factory() as session:
        records = await insert_operational_fixtures(session, ids)
        local = next(o for o in records if o.mode.value == "LOCAL")
        # TEST-only paid historical setup; never executed against the normal DB.
        await session.execute(
            text(
                "INSERT INTO payments(order_id,method_type,amount,status,paid_at) "
                "VALUES (:order,'CASH',:amount,'PAID',now())"
            ),
            {"order": local.id, "amount": local.total},
        )
        await session.execute(
            text(
                "UPDATE orders SET status='SERVED',payment_status='PAID' WHERE "
                "id=:order"
            ),
            {"order": local.id},
        )
        await session.commit()
        return local


def test_phase11_real_schema_constraints_scopes_and_empty_safe_downgrade(request):
    url = guarded_test_url(request)

    async def verify():
        async with database(url) as (engine, ids, factory):
            async with factory() as session:
                grants = set(
                    (
                        await session.execute(
                            text(
                                "SELECT r.code,p.code FROM role_permissions rp JOIN "
                                "roles r ON "
                                "r.id=rp.role_id JOIN permissions p ON "
                                "p.id=rp.permission_id "
                                "WHERE p.code IN "
                                "('REVIEW_VIEW','RECEIPT_VIEW','RECEIPT_MANAGE',"
                                "'PROMOTION_VIEW','PROMOTION_MANAGE','PROMOTION_REDEEM')"
                            )
                        )
                    ).all()
                )
                assert grants == {("ADMIN", p) for p in PERMISSIONS}
                await session.rollback()
            async with engine.begin() as connection:
                await connection.run_sync(
                    lambda sync: migration(sync, "0010_admin", downgrade=True)
                )
                assert (
                    len(
                        await connection.run_sync(
                            lambda sync: inspect(sync).get_table_names()
                        )
                    )
                    == 51
                )
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "0010_admin"
                )
                await connection.run_sync(
                    lambda sync: migration(sync, "0011_customer_extras")
                )
                assert (
                    len(
                        await connection.run_sync(
                            lambda sync: inspect(sync).get_table_names()
                        )
                    )
                    == 60
                )

    asyncio.run(verify())


def test_phase11_real_reviews_paid_receipts_atomicity_and_history_guard(request):
    url = guarded_test_url(request)

    async def verify():
        async with database(url) as (engine, ids, factory):
            local = await operational_fixture(factory, ids)
            async with factory() as session:
                reviews = ReviewService(
                    SQLAlchemyReviewRepository(session),
                    SQLAlchemyCustomerOrderReader(session),
                    SQLAlchemyBranchRepository(session),
                )
                row = await reviews.create(owner(ids), local.id, 5, "TEST Review")
                with pytest.raises(ConflictError):
                    await reviews.create(owner(ids), local.id, 1, None)
                for sql in (
                    "UPDATE order_reviews SET rating=1 WHERE id=:id",
                    "DELETE FROM order_reviews WHERE id=:id",
                ):
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(text(sql), {"id": row.id})
                await session.rollback()
                receipts = ReceiptService(
                    SQLAlchemyFiscalDocumentRepository(session),
                    SQLAlchemyCustomerOrderReader(session),
                    SQLAlchemyBranchRepository(session),
                    SQLAlchemyAuditRecorder(session),
                    UnconfiguredFiscalDocumentGateway(),
                )
                doc = await receipts.request(
                    owner(ids), local.id, "one", {"document_type": "BOLETA"}
                )
                assert (
                    await receipts.request(
                        owner(ids), local.id, "one", {"document_type": "BOLETA"}
                    )
                ).id == doc.id
                with pytest.raises(FiscalProviderUnavailable):
                    await receipts.process(admin(ids), ids["branch"], doc.id, "attempt")
                assert (await receipts.get(owner(ids), local.id)).status == "PENDING"
                assert (
                    await session.scalar(
                        text("SELECT count(*) FROM fiscal_document_attempts")
                    )
                    == 0
                )
                await session.rollback()

                # Both updates rolled back even though a verified provider result
                # exists.
                class FailingFinalization(SQLAlchemyFiscalDocumentRepository):
                    async def finish_attempt(self, *args):
                        await super().finish_attempt(*args)
                        raise RuntimeError("TEST after both fiscal writes")

                gateway = TestFiscalGateway(session)
                receipts.repository = FailingFinalization(session)
                receipts.gateway = gateway
                with pytest.raises(RuntimeError):
                    await receipts.process(admin(ids), ids["branch"], doc.id, "attempt")
                assert (await receipts.get(owner(ids), local.id)).status == "PROCESSING"
                assert (
                    await session.scalar(
                        text("SELECT status FROM fiscal_document_attempts")
                    )
                    == "PROCESSING"
                )
                await session.rollback()
                receipts.repository = SQLAlchemyFiscalDocumentRepository(session)
                issued = await receipts.process(
                    admin(ids), ids["branch"], doc.id, "attempt"
                )
                assert (
                    issued.status == "ISSUED" and gateway.calls == gateway.lookups == 1
                )
                for sql in (
                    "DELETE FROM fiscal_documents WHERE id=:id",
                    "UPDATE fiscal_documents SET amount=amount+1 WHERE id=:id",
                ):
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(text(sql), {"id": doc.id})
                await session.rollback()
            with pytest.raises(DBAPIError):
                async with engine.begin() as connection:
                    await connection.run_sync(
                        lambda sync: migration(sync, "0010_admin", downgrade=True)
                    )
            async with engine.connect() as connection:
                assert TABLES <= set(
                    await connection.run_sync(
                        lambda sync: inspect(sync).get_table_names()
                    )
                )
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "0011_customer_extras"
                )

    asyncio.run(verify())


class TestFiscalGateway:
    __test__ = False
    provider_code = "test_fiscal"

    def __init__(self, session):
        self.session = session
        self.calls = self.lookups = 0

    def response(self, request):
        assert not self.session.in_transaction()
        return FiscalResult(
            document_id=request.document_id,
            attempt_id=request.attempt_id,
            provider_code=self.provider_code,
            status="ISSUED",
            verified=True,
            amount=request.amount,
            currency_code="PEN",
            series="TEST",
            number=str(request.document_id),
            provider_reference=str(request.document_id),
            issued_at=utc_now(),
        )

    async def issue(self, request):
        self.calls += 1
        return self.response(request)

    async def lookup(self, request):
        self.lookups += 1
        return self.response(request)


class Rendezvous:
    def __init__(self):
        self.count = 0
        self.ready = asyncio.Event()

    async def wait(self):
        self.count += 1
        if self.count == 2:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), 3)


class RacingCampaignRepository(SQLAlchemyPromotionRepository):
    def __init__(self, session, barrier):
        super().__init__(session)
        self.barrier = barrier

    async def active_campaign(self, *args, **kwargs):
        if kwargs.get("lock"):
            await self.barrier.wait()
        return await super().active_campaign(*args, **kwargs)


@pytest.mark.parametrize("case", ["same_key", "cooldown", "last_prize"])
def test_real_two_connection_first_participation_and_spin_races(request, case):
    url = guarded_test_url(request)

    async def verify():
        async with database(url) as (_, ids, factory):
            campaign, prize, now = await campaign_fixture(
                factory,
                ids,
                cooldown=60 if case == "cooldown" else 0,
                max_awards=1 if case == "last_prize" else None,
            )
            second = owner(ids)
            if case == "last_prize":
                async with factory() as session:
                    other = await session.scalar(
                        text(
                            "INSERT INTO customers(full_name,phone) "
                            "VALUES ('TEST Other','+519000001111') RETURNING id"
                        )
                    )
                    await session.commit()
                    second = replace(second, customer_id=other)
            barrier = Rendezvous()
            async with factory() as a, factory() as b:
                pids = await asyncio.gather(
                    a.scalar(text("SELECT pg_backend_pid()")),
                    b.scalar(text("SELECT pg_backend_pid()")),
                )
                assert pids[0] != pids[1]
                await a.rollback()
                await b.rollback()
                rng_a, rng_b = Random(), Random()
                s_a = promotion_service(
                    a, RacingCampaignRepository(a, barrier), rng_a, now
                )
                s_b = promotion_service(
                    b, RacingCampaignRepository(b, barrier), rng_b, now
                )
                results = await asyncio.gather(
                    s_a.spin(owner(ids), ids["branch"], "one"),
                    s_b.spin(
                        second, ids["branch"], "one" if case == "same_key" else "two"
                    ),
                    return_exceptions=True,
                )
                if case == "cooldown":
                    assert sum(isinstance(r, ConflictError) for r in results) == 1
                elif case == "same_key":
                    assert results[0]["spin_id"] == results[1]["spin_id"]
                    assert rng_a.calls + rng_b.calls == 1
                else:
                    assert sorted(r["outcome"] for r in results) == ["NO_PRIZE", "WIN"]
            async with factory() as session:
                spin_count = await session.scalar(
                    text("SELECT count(*) FROM roulette_spins")
                )
                assert spin_count == (2 if case == "last_prize" else 1)
                assert await session.scalar(
                    text("SELECT count(*) FROM roulette_participations")
                ) == (2 if case == "last_prize" else 1)
                assert (
                    await session.scalar(
                        text("SELECT awarded_count FROM roulette_prizes WHERE id=:id"),
                        {"id": prize.id},
                    )
                    == 1
                )
                assert (
                    await session.scalar(text("SELECT count(*) FROM customer_rewards"))
                    == 1
                )
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(
                            text("UPDATE roulette_spins SET random_draw=9")
                        )
                await session.rollback()

    asyncio.run(verify())


def test_phase11_real_favorite_upsert_probability_active_campaign_and_double_redeem(
    request,
):
    url = guarded_test_url(request)

    async def verify():
        async with database(url) as (_, ids, factory):
            async with factory() as a, factory() as b:
                pids = await asyncio.gather(
                    a.scalar(text("SELECT pg_backend_pid()")),
                    b.scalar(text("SELECT pg_backend_pid()")),
                )
                assert pids[0] != pids[1]
                await a.rollback()
                await b.rollback()

                async def put(session):
                    repo = SQLAlchemyFavoriteRepository(session)
                    row = await repo.add_favorite(ids["actor"], ids["product"])
                    await repo.commit()
                    return row

                one, two = await asyncio.gather(put(a), put(b))
                assert one.id == two.id
            campaign, prize, now = await campaign_fixture(factory, ids)
            async with factory() as session:
                service = promotion_service(session, now=now)
                # Service-level sum check and PostgreSQL trigger independently agree.
                with pytest.raises(ConflictError):
                    await service.change_prize(
                        admin(ids),
                        ids["branch"],
                        campaign.id,
                        {
                            "product_id": ids["product"],
                            "display_name": "Excess",
                            "probability_bps": 9500,
                        },
                    )
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(
                            text(
                                "INSERT INTO "
                                "roulette_prizes(campaign_id,product_id,"
                                "display_name,probability_bps) "
                                "VALUES (:campaign,:product,'Excess',9500)"
                            ),
                            {"campaign": campaign.id, "product": ids["product"]},
                        )
                await session.rollback()
                draft = await service.create_campaign(
                    admin(ids),
                    ids["branch"],
                    {
                        "name": "Other",
                        "terms_text": "Free",
                        "starts_at": now,
                        "spin_cooldown_seconds": 0,
                    },
                )
                await service.change_prize(
                    admin(ids),
                    ids["branch"],
                    draft.id,
                    {
                        "product_id": ids["product"],
                        "display_name": "Other",
                        "probability_bps": 1,
                    },
                )
                with pytest.raises(DBAPIError):
                    async with session.begin_nested():
                        await session.execute(
                            text(
                                "UPDATE roulette_campaigns SET is_active=true WHERE "
                                "id=:id"
                            ),
                            {"id": draft.id},
                        )
                await session.rollback()
                reward = (await service.spin(owner(ids), ids["branch"], "one"))[
                    "reward"
                ]
            async with factory() as a, factory() as b:
                results = await asyncio.gather(
                    promotion_service(a, now=now).redeem(
                        admin(ids), ids["branch"], reward.id
                    ),
                    promotion_service(b, now=now).redeem(
                        admin(ids), ids["branch"], reward.id
                    ),
                )
                assert results[0].redeemed_at == results[1].redeemed_at
            async with factory() as session:
                assert (
                    await session.scalar(
                        text(
                            "SELECT count(*) FROM audit_logs WHERE "
                            "action='ROULETTE_REWARD_REDEEMED'"
                        )
                    )
                    == 1
                )
                await session.execute(
                    text(
                        "UPDATE staff_assignments SET is_active=false WHERE "
                        "user_id=:actor"
                    ),
                    ids,
                )
                await session.commit()
                with pytest.raises(ForbiddenError):
                    await promotion_service(session, now=now).list_campaigns(
                        admin(ids), ids["branch"]
                    )

    asyncio.run(verify())
