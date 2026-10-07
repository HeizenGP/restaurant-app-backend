import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.branches.infrastructure.customer_operations import (
    SQLAlchemyCustomerBranchReader,
)
from app.modules.promotions.infrastructure.persistence.repositories import (
    SQLAlchemyPromotionRepository,
)
from app.shared.application.exceptions import ConflictError
from tests.modules.admin.test_repositories import result
from tests.modules.extras_factories import promotion_setup
from tests.modules.extras_support import NOW


def test_branch_shared_barrier_and_campaign_exclusive_lock():
    session = AsyncMock()
    session.execute.return_value = result()
    branch, id_ = uuid4(), uuid4()
    asyncio.run(
        SQLAlchemyCustomerBranchReader(session).customer_branch(branch, lock=True)
    )
    sql, params = session.execute.await_args.args
    assert "is_active AND deleted_at IS NULL" in str(sql) and "FOR SHARE" in str(sql)
    assert params == {"id": branch}
    repo = SQLAlchemyPromotionRepository(session)
    asyncio.run(repo.active_campaign(branch, lock=True))
    assert "is_active IS TRUE FOR UPDATE" in str(session.execute.await_args.args[0])
    asyncio.run(repo.campaign(branch, id_, lock=True))
    assert "branch_id=:branch AND id=:id FOR UPDATE" in str(
        session.execute.await_args.args[0]
    )


def test_first_participation_unique_upsert_before_lock_and_owner_namespace():
    session = AsyncMock()
    session.execute.return_value = result()
    campaign, customer = uuid4(), uuid4()
    asyncio.run(
        SQLAlchemyPromotionRepository(session).participation(
            campaign, customer, lock=True
        )
    )
    calls = session.execute.await_args_list
    assert len(calls) == 2 and "ON CONFLICT(campaign_id,customer_id) DO NOTHING" in str(
        calls[0].args[0]
    )
    assert "customer_id=:customer FOR UPDATE" in str(calls[1].args[0])
    assert (
        calls[0].args[1]
        == calls[1].args[1]
        == {"campaign": campaign, "customer": customer}
    )


def test_spin_retry_owner_branch_hash_and_reward_queries_scoped_before_page():
    session = AsyncMock()
    session.execute.return_value = result(mappings=[])
    repo = SQLAlchemyPromotionRepository(session)
    branch, customer, id_ = uuid4(), uuid4(), uuid4()
    asyncio.run(repo.find_spin(branch, customer, "a" * 64))
    assert session.execute.await_args.args[1] == {
        "branch": branch,
        "customer": customer,
        "key": "a" * 64,
    }
    asyncio.run(repo.rewards(customer, 50, 0))
    sql = str(session.execute.await_args.args[0])
    assert sql.index("customer_id=:customer") < sql.index("LIMIT :limit")
    asyncio.run(repo.branch_reward(branch, id_, lock=True))
    assert "branch_id=:branch AND id=:id FOR UPDATE" in str(
        session.execute.await_args.args[0]
    )


@pytest.mark.parametrize("exhausted", [True, False])
def test_conditional_award_counter_and_reward_insert_are_one_caller_transaction(
    exhausted,
):
    async def verify():
        s = promotion_setup()
        spun = await s.service.spin(s.customer, s.branch, "one")
        spin = next(iter(s.repo.state.spins.values()))
        prize = {
            "id": s.prize.id,
            "product_id": s.prize.product_id,
            "product_name": "Original product",
        }
        session = AsyncMock()
        session.scalar.return_value = None if exhausted else s.prize.id
        session.execute.return_value = result(mapping=asdict(spun["reward"]))
        repo = SQLAlchemyPromotionRepository(session)
        if exhausted:
            with pytest.raises(ConflictError):
                await repo.award(spin, prize, None)
            assert session.execute.await_count == 0
        else:
            assert await repo.award(spin, prize, None) == spun["reward"]
            assert session.execute.await_args.args[1]["customer"] == spin.customer_id
        sql = str(session.scalar.await_args.args[0])
        assert (
            "awarded_count=awarded_count+1" in sql and "awarded_count<max_awards" in sql
        )
        session.commit.assert_not_called()

    asyncio.run(verify())


def test_redeem_bound_actor_and_conditional_state_without_implicit_commit():
    async def verify():
        s = promotion_setup()
        row = (await s.service.spin(s.customer, s.branch, "one"))["reward"]
        session = AsyncMock()
        session.execute.return_value = result(mapping=asdict(row))
        await SQLAlchemyPromotionRepository(session).redeem_reward(
            row.id, s.admin.user_id, NOW
        )
        sql, params = session.execute.await_args.args
        assert "WHERE id=:id AND status='AVAILABLE'" in str(sql)
        assert params == {"id": row.id, "actor": s.admin.user_id, "now": NOW}
        session.commit.assert_not_called()

    asyncio.run(verify())
