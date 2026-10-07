import asyncio
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.promotions.application.services import PromotionService
from app.modules.promotions.domain.policies import (
    campaign_values,
    effective_prizes,
    participation_state,
    prize_values,
    select_prize,
)
from app.modules.promotions.infrastructure.random_source import SecretsRandomSource
from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
)
from tests.modules.extras_factories import promotion_setup
from tests.modules.extras_support import NOW, Promotions, Random, principal


def set_campaign(s, **values):
    s.campaign = replace(s.campaign, **values)
    s.repo.state.campaigns[s.campaign.id] = s.campaign


def set_prize(s, **values):
    s.prize = replace(s.prize, **values)
    s.repo.state.prizes[s.prize.id] = s.prize


def test_exact_probability_histogram_boundaries_and_remainder_not_normalized():
    s = promotion_setup()
    other = replace(s.prize, id=uuid4(), probability_bps=500, sort_order=1)
    config = effective_prizes(
        [other, s.prize], {s.catalog.product.id: s.catalog.product}
    )
    results = Counter(
        value["id"] if (value := select_prize(draw, config)) else None
        for draw in range(10000)
    )
    assert results == {s.prize.id: 1000, other.id: 500, None: 8500}
    assert select_prize(999, config)["id"] == s.prize.id
    assert select_prize(1000, config)["id"] == other.id
    assert select_prize(1499, config)["id"] == other.id
    assert select_prize(1500, config) is None


@pytest.mark.parametrize("reason", ["exhausted", "hidden", "sold_out", "inactive"])
def test_unavailable_intervals_become_no_prize_without_redistribution(reason):
    s = promotion_setup()
    other = replace(s.prize, id=uuid4(), probability_bps=500, sort_order=1)
    products = {s.catalog.product.id: s.catalog.product}
    first = s.prize
    if reason == "exhausted":
        first = replace(first, max_awards=1, awarded_count=1)
    elif reason == "hidden":
        first = replace(first, product_id=uuid4())
    elif reason == "sold_out":
        first = replace(first, product_id=uuid4())
        products[first.product_id] = replace(
            s.catalog.product, id=first.product_id, is_available=False
        )
    else:
        first = replace(first, is_active=False)
    config = effective_prizes([other, first], products)
    assert config[0]["effective_probability_bps"] == 0
    assert config[1]["effective_probability_bps"] == 500
    assert sum(select_prize(d, config) is not None for d in range(10000)) == 500
    assert config[1]["start"] == (0 if reason == "inactive" else 1000)


@pytest.mark.parametrize("draw", [-1, 10000, True, 0.5, "0", None])
def test_invalid_random_draw_rejected(draw):
    with pytest.raises(ValueError):
        select_prize(draw, [])


def test_csprng_uses_exact_secrets_randbelow_not_general_random(monkeypatch):
    values = []
    monkeypatch.setattr(
        "app.modules.promotions.infrastructure.random_source.secrets.randbelow",
        lambda maximum: values.append(maximum) or 9999,
    )
    assert SecretsRandomSource().draw() == 9999 and values == [10000]


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"customer_id": uuid4()},
        {"spin_cooldown_seconds": True},
        {"spin_cooldown_seconds": -1},
        {"max_spins_per_customer_per_day": 0},
        {"reward_validity_days": 0},
        {"starts_at": datetime(2026, 10, 7)},
        {"name": " "},
        {"terms_text": "<html>"},
        {"is_active": "yes"},
        {"spin_cooldown_seconds": 2147483648},
    ],
)
def test_invalid_campaign_configuration(values):
    with pytest.raises(ValueError):
        campaign_values(values, creating=False)


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"awarded_count": 0},
        {"campaign_id": uuid4()},
        {"product_id": "abc"},
        {"probability_bps": True},
        {"probability_bps": 1.5},
        {"probability_bps": -1},
        {"probability_bps": 10001},
        {"max_awards": -1},
        {"sort_order": -1},
        {"display_name": " "},
        {"is_active": 1},
    ],
)
def test_invalid_prize_configuration(values):
    with pytest.raises(ValueError):
        prize_values(values)


@pytest.mark.parametrize("guest", [True, False])
@pytest.mark.parametrize(
    "draw,expected", [(0, "WIN"), (999, "WIN"), (1000, "NO_PRIZE"), (9999, "NO_PRIZE")]
)
def test_spin_outcome_server_owned_free_immutable_historical_and_idempotent(
    guest, draw, expected
):
    async def verify():
        s = promotion_setup(customer=principal(guest=guest))
        s.random.value = draw
        first = await s.service.spin(s.customer, s.branch, "spin-1")
        stored = next(iter(s.repo.state.spins.values()))
        assert first["outcome"] == expected and stored.random_draw == draw
        assert (
            stored.campaign_version == 1
            and stored.configuration_snapshot["no_prize_probability_bps"] == 9000
        )
        assert len(stored.idempotency_key) == 64 and s.random.calls == 1
        assert len(s.catalog.batches) == 1 and not s.audit.records
        assert len(s.repo.state.participations) == len(s.repo.state.spins) == 1
        assert len(s.repo.state.rewards) == (expected == "WIN")
        if expected == "WIN":
            reward = first["reward"]
            assert reward.product_name_snapshot == "Original product"
            assert reward.expires_at == NOW + timedelta(days=2)
            assert first["prize"]["product_name"] == "Original product"
        else:
            assert first["reward"] is first["prize"] is None
        # Configuration, branch, product or draw changes never reroll stored outcomes.
        set_campaign(s, is_active=False, version=99)
        s.branches.branch = replace(s.branches.branch, is_active=False)
        s.catalog.hidden = True
        s.random.value = 9999 if draw == 0 else 0
        assert await s.service.spin(s.customer, s.branch, "spin-1") == first
        assert s.random.calls == 1 and len(s.repo.state.spins) == 1
        assert next(iter(s.repo.state.spins.values())) == stored

    asyncio.run(verify())


def test_public_configuration_visible_terms_decimal_probabilities_and_owner_frequency():
    async def verify():
        s = promotion_setup()
        result = await s.service.roulette(s.customer, s.branch)
        assert result["terms_text"] == s.campaign.terms_text and result["can_spin"]
        assert result["no_prize_probability_percent"] == Decimal("90")
        assert isinstance(result["prizes"][0]["probability_percent"], Decimal)
        assert result["prizes"][0]["probability_percent"] == Decimal("10")
        assert len(s.catalog.batches) == 1
        s.catalog.hidden = True
        result = await s.service.roulette(s.customer, s.branch)
        assert result["no_prize_probability_bps"] == 10000
        assert not result["prizes"][0]["is_available"]

    asyncio.run(verify())


@pytest.mark.parametrize(
    "changes",
    [{"is_active": False}, {"starts_at": NOW + timedelta(seconds=1)}, {"ends_at": NOW}],
)
def test_unplayable_campaign_no_spin_or_rng(changes):
    async def verify():
        s = promotion_setup()
        set_campaign(s, **changes)
        with pytest.raises(ConflictError) as error:
            await s.service.spin(s.customer, s.branch, "one")
        assert error.value.code == "ROULETTE_NOT_AVAILABLE"
        assert (
            not s.repo.state.spins
            and not s.repo.state.participations
            and s.random.calls == 0
        )

    asyncio.run(verify())


def test_cooldown_inclusive_boundary_and_daily_limit_local_day_reset():
    async def verify():
        s = promotion_setup()
        set_campaign(s, spin_cooldown_seconds=60, max_spins_per_customer_per_day=2)
        await s.service.spin(s.customer, s.branch, "one")
        s.clock.now = NOW + timedelta(seconds=59)
        with pytest.raises(ConflictError) as error:
            await s.service.spin(s.customer, s.branch, "two")
        assert error.value.code == "ROULETTE_COOLDOWN_ACTIVE"
        assert await s.service.spin(s.customer, s.branch, "one")
        s.clock.now = NOW + timedelta(seconds=60)
        await s.service.spin(s.customer, s.branch, "two")
        s.clock.now = NOW + timedelta(seconds=120)
        with pytest.raises(ConflictError) as error:
            await s.service.spin(s.customer, s.branch, "three")
        assert error.value.code == "ROULETTE_DAILY_LIMIT_REACHED"
        data = await s.service.roulette(s.customer, s.branch)
        assert data["next_spin_at"] == datetime(2026, 10, 8, 5, tzinfo=UTC)
        s.clock.now = data["next_spin_at"] - timedelta(microseconds=1)
        with pytest.raises(ConflictError):
            await s.service.spin(s.customer, s.branch, "three")
        s.clock.now = data["next_spin_at"]
        await s.service.spin(s.customer, s.branch, "three")
        participation = next(iter(s.repo.state.participations.values()))
        assert participation.spins_today == 1 and len(s.repo.state.spins) == 3

    asyncio.run(verify())


@pytest.mark.parametrize(
    "timezone,now,reset",
    [
        (
            "America/Lima",
            datetime(2026, 10, 8, 4, tzinfo=UTC),
            datetime(2026, 10, 8, 5, tzinfo=UTC),
        ),
        (
            "America/New_York",
            datetime(2026, 3, 8, 6, tzinfo=UTC),
            datetime(2026, 3, 9, 4, tzinfo=UTC),
        ),
        (
            "America/New_York",
            datetime(2026, 11, 1, 5, tzinfo=UTC),
            datetime(2026, 11, 2, 5, tzinfo=UTC),
        ),
    ],
)
def test_daily_timezone_dst_not_fixed_utc_24_hours(timezone, now, reset):
    async def verify():
        s = promotion_setup()
        set_campaign(
            s, max_spins_per_customer_per_day=1, starts_at=now - timedelta(days=1)
        )
        s.branches.branch = replace(s.branches.branch, timezone=timezone)
        s.clock.now = now
        await s.service.spin(s.customer, s.branch, "one")
        p = next(iter(s.repo.state.participations.values()))
        _, count, next_at, _, daily = participation_state(s.campaign, p, now, timezone)
        assert count == 1 and daily and next_at == reset

    asyncio.run(verify())


def test_reward_expiry_is_lazy_no_read_write_and_redemption_idempotent_by_admin_only():
    async def verify():
        s = promotion_setup()
        first = await s.service.spin(s.customer, s.branch, "one")
        reward = first["reward"]
        assert await s.service.rewards(principal()) == []
        with pytest.raises(ForbiddenError):
            await s.service.redeem(s.customer, s.branch, reward.id)
        with pytest.raises(ForbiddenError):
            await s.service.redeem(s.admin, uuid4(), reward.id)
        with pytest.raises(NotFoundError):
            await s.service.redeem(s.admin, s.branch, uuid4())
        result = await s.service.redeem(s.admin, s.branch, reward.id)
        assert (
            result.status == "REDEEMED"
            and result.redeemed_by_user_id == s.admin.user_id
        )
        s.clock.now += timedelta(days=4)
        assert await s.service.redeem(s.admin, s.branch, reward.id) == result
        assert len(s.audit.records) == 1
        assert s.audit.records[0].after_state == {"status": "REDEEMED"}
        assert (await s.service.rewards(s.customer))[0].status == "REDEEMED"

    asyncio.run(verify())


def test_expired_reward_rejected_at_exact_boundary_projection_does_not_mutate_history():
    async def verify():
        s = promotion_setup()
        result = await s.service.spin(s.customer, s.branch, "one")
        reward = result["reward"]
        before = s.repo.commits
        s.clock.now = reward.expires_at
        assert (await s.service.rewards(s.customer))[0].status == "EXPIRED"
        assert (
            s.repo.state.rewards[reward.id].status == "AVAILABLE"
            and s.repo.commits == before
        )
        assert (await s.service.spin(s.customer, s.branch, "one"))[
            "reward"
        ].status == "EXPIRED"
        with pytest.raises(ConflictError) as error:
            await s.service.redeem(s.admin, s.branch, reward.id)
        assert error.value.code == "ROULETTE_REWARD_EXPIRED"
        assert not s.audit.records

    asyncio.run(verify())


def test_null_validity_never_expires():
    async def verify():
        s = promotion_setup()
        set_campaign(s, reward_validity_days=None)
        result = await s.service.spin(s.customer, s.branch, "one")
        assert result["reward"].expires_at is None
        s.clock.now += timedelta(days=1000)
        assert (await s.service.rewards(s.customer))[0].status == "AVAILABLE"

    asyncio.run(verify())


def test_atomic_spin_failure_rolls_back_participation_award_and_reward():
    async def verify():
        s = promotion_setup()
        s.repo.state.fail_reward = True
        with pytest.raises(RuntimeError):
            await s.service.spin(s.customer, s.branch, "one")
        assert (
            not s.repo.state.spins
            and not s.repo.state.participations
            and not s.repo.state.rewards
        )
        assert s.repo.state.prizes[s.prize.id].awarded_count == 0
        s.repo.state.fail_reward = False
        assert (await s.service.spin(s.customer, s.branch, "one"))["outcome"] == "WIN"

    asyncio.run(verify())


@pytest.mark.parametrize("same_key,cooldown", [(True, 0), (False, 60), (False, 0)])
def test_concurrent_first_participation_in_memory_contract_not_postgres_proof(
    same_key, cooldown
):
    async def verify():
        s = promotion_setup()
        set_campaign(s, spin_cooldown_seconds=cooldown)
        other_repo, other_rng = Promotions(s.repo.state), Random()
        other = PromotionService(
            other_repo,
            s.branches,
            s.authorization,
            s.catalog,
            s.audit,
            other_rng,
            s.clock,
        )
        results = await asyncio.gather(
            s.service.spin(s.customer, s.branch, "one"),
            other.spin(s.customer, s.branch, "one" if same_key else "two"),
            return_exceptions=True,
        )
        if same_key:
            assert results[0]["spin_id"] == results[1]["spin_id"]
            assert (
                len(s.repo.state.spins) == 1 and s.random.calls + other_rng.calls == 1
            )
        elif cooldown:
            assert sum(isinstance(r, ConflictError) for r in results) == 1
            assert len(s.repo.state.spins) == 1
        else:
            assert len(s.repo.state.spins) == 2
        assert len(s.repo.state.participations) == 1

    asyncio.run(verify())


def test_last_prize_double_redeem_memory_serialization_not_real_db_races():
    async def verify():
        s = promotion_setup()
        set_prize(s, max_awards=1)
        other_repo = Promotions(s.repo.state)
        other = PromotionService(
            other_repo,
            s.branches,
            s.authorization,
            s.catalog,
            s.audit,
            Random(),
            s.clock,
        )
        results = await asyncio.gather(
            s.service.spin(s.customer, s.branch, "one"),
            other.spin(principal(), s.branch, "two"),
        )
        assert Counter(r["outcome"] for r in results) == {"WIN": 1, "NO_PRIZE": 1}
        assert (
            s.repo.state.prizes[s.prize.id].awarded_count
            == len(s.repo.state.rewards)
            == 1
        )
        reward = next(r["reward"] for r in results if r["reward"])
        a, b = await asyncio.gather(
            s.service.redeem(s.admin, s.branch, reward.id),
            other.redeem(s.admin, s.branch, reward.id),
        )
        assert a == b and len(s.audit.records) == 1

    asyncio.run(verify())


def test_admin_config_draft_prize_version_activation_scope_soft_delete_safe_audit():
    async def verify():
        s = promotion_setup()
        set_campaign(s, is_active=False)
        data = {
            "name": " New ",
            "terms_text": " Free ",
            "starts_at": NOW,
            "spin_cooldown_seconds": 30,
            "reward_validity_days": None,
        }
        draft = await s.service.create_campaign(s.admin, s.branch, data)
        assert not draft.is_active and draft.name == "New"
        with pytest.raises(ConflictError):
            await s.service.change_campaign(
                s.admin, s.branch, draft.id, {"is_active": True}
            )
        prize = await s.service.change_prize(
            s.admin,
            s.branch,
            draft.id,
            {
                "product_id": s.catalog.product.id,
                "display_name": "New prize",
                "probability_bps": 500,
            },
        )
        updated = await s.service.change_campaign(
            s.admin, s.branch, draft.id, {"is_active": True}
        )
        assert updated.version == 3
        with pytest.raises(ConflictError):
            await s.service.change_campaign(
                s.admin, s.branch, s.campaign.id, {"is_active": True}
            )
        before = s.repo.state.campaigns[draft.id].version
        result = await s.service.change_prize(
            s.admin, s.branch, draft.id, {"is_active": False}, prize.id
        )
        assert not result.is_active and prize.id in s.repo.state.prizes
        assert s.repo.state.campaigns[draft.id].version == before + 1
        s.catalog.hidden = True
        await s.service.change_prize(
            s.admin, s.branch, draft.id, {"is_active": False}, prize.id
        )
        with pytest.raises(ForbiddenError):
            await s.service.get_campaign(s.admin, uuid4(), draft.id)
        assert not any("TEST Fiscal" in str(r) for r in s.audit.records)
        assert {r.action for r in s.audit.records} >= {
            "ROULETTE_CAMPAIGN_CREATED",
            "ROULETTE_PRIZE_CREATED",
            "ROULETTE_CAMPAIGN_ACTIVATED",
            "ROULETTE_PRIZE_DEACTIVATED",
        }

    asyncio.run(verify())


def test_prize_total_limits_hidden_product_and_awards_cannot_be_erased():
    async def verify():
        s = promotion_setup()
        original = s.repo.state.prizes[s.prize.id]
        with pytest.raises(ConflictError) as error:
            await s.service.change_prize(
                s.admin,
                s.branch,
                s.campaign.id,
                {
                    "product_id": s.catalog.product.id,
                    "display_name": "Extra",
                    "probability_bps": 9001,
                },
            )
        assert error.value.code == "ROULETTE_PROBABILITY_TOTAL_EXCEEDED"
        assert s.repo.state.prizes == {original.id: original}
        s.catalog.hidden = True
        with pytest.raises(ConflictError):
            await s.service.change_prize(
                s.admin, s.branch, s.campaign.id, {"is_active": True}, s.prize.id
            )
        s.catalog.hidden = False
        await s.service.spin(s.customer, s.branch, "one")
        with pytest.raises(RequestDataError):
            await s.service.change_prize(
                s.admin, s.branch, s.campaign.id, {"max_awards": 0}, s.prize.id
            )
        assert s.repo.state.prizes[s.prize.id].awarded_count == 1

    asyncio.run(verify())


def test_configuration_audit_failure_and_permission_recheck_rollback():
    async def verify():
        s = promotion_setup()
        s.audit.fail = True
        with pytest.raises(RuntimeError):
            await s.service.change_campaign(
                s.admin, s.branch, s.campaign.id, {"name": "Changed"}
            )
        assert s.repo.state.campaigns[s.campaign.id] == s.campaign
        s.audit.fail = False
        original = s.branches.customer_branch

        async def revoked(*args, **kwargs):
            result = await original(*args, **kwargs)
            s.authorization.enabled = False
            return result

        s.branches.customer_branch = revoked
        with pytest.raises(ForbiddenError):
            await s.service.change_prize(
                s.admin, s.branch, s.campaign.id, {"probability_bps": 500}, s.prize.id
            )
        assert s.repo.state.prizes[s.prize.id] == s.prize

    asyncio.run(verify())
