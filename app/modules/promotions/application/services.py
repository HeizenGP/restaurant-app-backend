from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.branches.application.customer_operations import CustomerBranchReader
from app.modules.promotions.application.ports import (
    PrizeCatalog,
    PromotionRepository,
    SecureRandomPort,
)
from app.modules.promotions.domain.models import RouletteCampaign
from app.modules.promotions.domain.policies import (
    campaign_values,
    campaign_window,
    effective_prizes,
    participation_state,
    prize_values,
    reward_view,
    select_prize,
)
from app.shared.application.administration import (
    AdministrationAuthorization,
    AdministrationConflict,
    AdministrationNotFound,
    require_administration,
)
from app.shared.application.audit import AuditRecord, AuditRecorder
from app.shared.application.customer_identity import (
    customer_identity,
    idempotency_digest,
)
from app.shared.application.exceptions import RequestDataError
from app.shared.domain.time import utc_now


class PromotionService:
    def __init__(
        self,
        repository: PromotionRepository,
        branches: CustomerBranchReader,
        authorization: AdministrationAuthorization,
        catalog: PrizeCatalog,
        audit: AuditRecorder,
        random: SecureRandomPort,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.repository, self.branches, self.authorization = (
            repository,
            branches,
            authorization,
        )
        self.catalog, self.audit, self.random, self.clock = (
            catalog,
            audit,
            random,
            clock,
        )

    async def _branch(self, branch_id, *, lock=False):
        branch = await self.branches.customer_branch(branch_id, lock=lock)
        if branch is None or not branch.is_active:
            raise AdministrationNotFound("BRANCH_NOT_FOUND", "Branch not found")
        return branch

    async def _campaign(self, branch_id, campaign_id, *, lock=False):
        campaign = await self.repository.campaign(branch_id, campaign_id, lock=lock)
        if campaign is None:
            raise AdministrationNotFound("ROULETTE_NOT_AVAILABLE", "Campaign not found")
        return campaign

    async def _configuration(self, campaign):
        prizes = await self.repository.prizes(campaign.id)
        products = await self.catalog.products(
            campaign.branch_id, tuple(p.product_id for p in prizes)
        )
        return effective_prizes(prizes, products)

    async def _audit(self, actor, branch_id, entity, action, before=None):
        await self.audit.record(
            AuditRecord(
                actor_user_id=actor,
                branch_id=branch_id,
                action=action,
                entity_type="ROULETTE_REWARD"
                if "REWARD" in action
                else "ROULETTE_PRIZE"
                if "PRIZE" in action
                else "ROULETTE_CAMPAIGN",
                entity_id=entity.id,
                before_state={"is_active": before.is_active}
                if before and hasattr(before, "is_active")
                else None,
                after_state={"version": entity.version}
                if hasattr(entity, "version")
                else {"status": entity.status}
                if hasattr(entity, "status")
                else {
                    "probability_bps": entity.probability_bps,
                    "is_active": entity.is_active,
                },
            )
        )

    async def list_campaigns(
        self, principal: Principal, branch_id: UUID, limit=50, offset=0
    ):
        await require_administration(
            self.authorization, principal, branch_id, "PROMOTION_VIEW"
        )
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise RequestDataError("Invalid pagination")
        return await self.repository.campaigns(branch_id, limit, offset)

    async def get_campaign(
        self, principal: Principal, branch_id: UUID, campaign_id: UUID
    ):
        await require_administration(
            self.authorization, principal, branch_id, "PROMOTION_VIEW"
        )
        campaign = await self._campaign(branch_id, campaign_id)
        return {**asdict(campaign), "prizes": await self.repository.prizes(campaign.id)}

    async def create_campaign(
        self, principal: Principal, branch_id: UUID, values: dict
    ):
        try:
            actor = await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_MANAGE"
            )
            await self._branch(branch_id, lock=True)
            await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_MANAGE"
            )
            try:
                values = campaign_values(values, creating=True)
                prototype = RouletteCampaign(
                    id=branch_id,
                    branch_id=branch_id,
                    created_by_user_id=actor,
                    name=values["name"],
                    terms_text=values["terms_text"],
                    is_active=False,
                    starts_at=values["starts_at"],
                    ends_at=values.get("ends_at"),
                    spin_cooldown_seconds=values["spin_cooldown_seconds"],
                    max_spins_per_customer_per_day=values.get(
                        "max_spins_per_customer_per_day"
                    ),
                    reward_validity_days=values.get("reward_validity_days"),
                    version=1,
                    created_at=self.clock(),
                    updated_at=self.clock(),
                )
                campaign_window(prototype)
            except (ValueError, TypeError):
                raise RequestDataError("Invalid campaign configuration") from None
            result = await self.repository.create_campaign(branch_id, actor, values)
            await self._audit(actor, branch_id, result, "ROULETTE_CAMPAIGN_CREATED")
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def change_campaign(
        self, principal: Principal, branch_id: UUID, campaign_id: UUID, values: dict
    ):
        try:
            actor = await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_MANAGE"
            )
            await self._branch(branch_id, lock=True)
            await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_MANAGE"
            )
            before = await self._campaign(branch_id, campaign_id, lock=True)
            try:
                values = campaign_values(values, creating=False)
                updated = replace(before, **values)
                campaign_window(updated)
            except (ValueError, TypeError):
                raise RequestDataError("Invalid campaign configuration") from None
            if updated.is_active and not before.is_active:
                prizes = await self._configuration(updated)
                if not any(p["effective_probability_bps"] > 0 for p in prizes):
                    raise AdministrationConflict(
                        "ROULETTE_NOT_AVAILABLE",
                        "Configure available prizes before activation",
                    )
            result = await self.repository.change_campaign(before.id, values)
            action = (
                "ROULETTE_CAMPAIGN_ACTIVATED"
                if result.is_active and not before.is_active
                else "ROULETTE_CAMPAIGN_DEACTIVATED"
                if not result.is_active and before.is_active
                else "ROULETTE_CAMPAIGN_UPDATED"
            )
            await self._audit(actor, branch_id, result, action, before)
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def change_prize(
        self,
        principal: Principal,
        branch_id: UUID,
        campaign_id: UUID,
        values: dict,
        prize_id: UUID | None = None,
    ):
        try:
            actor = await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_MANAGE"
            )
            await self._branch(branch_id, lock=True)
            await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_MANAGE"
            )
            campaign = await self._campaign(branch_id, campaign_id, lock=True)
            prizes = await self.repository.prizes(campaign.id)
            before = (
                next((p for p in prizes if p.id == prize_id), None)
                if prize_id
                else None
            )
            if prize_id and before is None:
                raise AdministrationNotFound(
                    "ROULETTE_PRIZE_UNAVAILABLE", "Prize not found"
                )
            try:
                values = prize_values(values)
                merged = {**asdict(before), **values} if before else values
                if (
                    not {"product_id", "display_name", "probability_bps"}
                    <= merged.keys()
                ):
                    raise ValueError("Missing prize data")
                if (
                    before
                    and merged.get("max_awards") is not None
                    and merged["max_awards"] < before.awarded_count
                ):
                    raise ValueError("Award limit cannot erase awards")
            except (ValueError, TypeError):
                raise RequestDataError("Invalid prize configuration") from None
            if not before and len(prizes) >= 100:
                raise AdministrationConflict(
                    "ROULETTE_CONFIG_LIMIT", "Campaign supports at most 100 prizes"
                )
            if not before or "product_id" in values or merged.get("is_active", True):
                products = await self.catalog.products(
                    branch_id, (merged["product_id"],)
                )
                product = products.get(merged["product_id"])
                if product is None or not product.is_available:
                    raise AdministrationConflict(
                        "ROULETTE_PRIZE_UNAVAILABLE",
                        "Product is not publicly available in this branch",
                    )
            total = sum(
                p.probability_bps
                for p in prizes
                if p.is_active and (not before or p.id != before.id)
            )
            if merged.get("is_active", True):
                total += merged["probability_bps"]
            if total > 10000:
                raise AdministrationConflict(
                    "ROULETTE_PROBABILITY_TOTAL_EXCEEDED",
                    "Active probabilities exceed 10000 basis points",
                )
            result = (
                await self.repository.change_prize(prize_id, values)
                if before
                else await self.repository.create_prize(campaign.id, values)
            )
            await self.repository.change_campaign(campaign.id, {})
            action = (
                "ROULETTE_PRIZE_CREATED"
                if not before
                else "ROULETTE_PRIZE_DEACTIVATED"
                if before.is_active and not result.is_active
                else "ROULETTE_PRIZE_UPDATED"
            )
            await self._audit(actor, branch_id, result, action, before)
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def roulette(self, principal: Principal, branch_id: UUID):
        customer = customer_identity(principal)
        branch = await self._branch(branch_id)
        campaign = await self.repository.active_campaign(branch_id)
        if campaign is None:
            raise AdministrationNotFound(
                "ROULETTE_NOT_AVAILABLE", "No active roulette campaign"
            )
        now = self.clock()
        participation = await self.repository.participation(campaign.id, customer)
        _, _, next_at, cooldown, daily = participation_state(
            campaign, participation, now, branch.timezone
        )
        prizes = await self._configuration(campaign)
        no_prize = 10000 - sum(p["effective_probability_bps"] for p in prizes)
        return {
            "campaign_id": campaign.id,
            "name": campaign.name,
            "terms_text": campaign.terms_text,
            "version": campaign.version,
            "starts_at": campaign.starts_at,
            "ends_at": campaign.ends_at,
            "spin_cooldown_seconds": campaign.spin_cooldown_seconds,
            "max_spins_per_customer_per_day": campaign.max_spins_per_customer_per_day,
            "reward_validity_days": campaign.reward_validity_days,
            "timezone": branch.timezone,
            "next_spin_at": next_at,
            "can_spin": not cooldown
            and not daily
            and now >= campaign.starts_at
            and (campaign.ends_at is None or now < campaign.ends_at),
            "prizes": [
                {
                    **p,
                    "probability_percent": Decimal(p["probability_bps"]) / 100,
                    "effective_probability_percent": Decimal(
                        p["effective_probability_bps"]
                    )
                    / 100,
                }
                for p in prizes
            ],
            "no_prize_probability_bps": no_prize,
            "no_prize_probability_percent": Decimal(no_prize) / 100,
        }

    async def _spin_response(self, spin):
        reward = await self.repository.spin_reward(spin.id)
        return {
            "spin_id": spin.id,
            "outcome": spin.outcome,
            "campaign_id": spin.campaign_id,
            "campaign_version": spin.campaign_version,
            "spun_at": spin.spun_at,
            "prize": {
                "id": reward.prize_id,
                "product_id": reward.product_id,
                "product_name": reward.product_name_snapshot,
            }
            if reward
            else None,
            "reward": reward_view(reward, self.clock()) if reward else None,
        }

    async def spin(self, principal: Principal, branch_id: UUID, key: str):
        customer = customer_identity(principal)
        try:
            key_hash = idempotency_digest(key)
            existing = await self.repository.find_spin(branch_id, customer, key_hash)
            if existing:
                result = await self._spin_response(existing)
                await self.repository.commit()
                return result
            branch = await self._branch(branch_id, lock=True)
            campaign = await self.repository.active_campaign(branch_id, lock=True)
            existing = await self.repository.find_spin(branch_id, customer, key_hash)
            if existing:
                result = await self._spin_response(existing)
                await self.repository.commit()
                return result
            now = self.clock()
            if (
                campaign is None
                or now < campaign.starts_at
                or (campaign.ends_at and now >= campaign.ends_at)
            ):
                raise AdministrationConflict(
                    "ROULETTE_NOT_AVAILABLE", "Roulette is not playable"
                )
            participation = await self.repository.participation(
                campaign.id, customer, lock=True
            )
            day, count, _, cooldown, daily = participation_state(
                campaign, participation, now, branch.timezone
            )
            if cooldown:
                raise AdministrationConflict(
                    "ROULETTE_COOLDOWN_ACTIVE", "Spin cooldown is active"
                )
            if daily:
                raise AdministrationConflict(
                    "ROULETTE_DAILY_LIMIT_REACHED", "Daily spin limit reached"
                )
            prizes = await self._configuration(campaign)
            draw = self.random.draw()
            winner = select_prize(draw, prizes)
            snapshot = {
                "campaign_version": campaign.version,
                "prizes": [
                    {
                        "prize_id": str(p["id"]),
                        "probability_bps": p["probability_bps"],
                        "is_available": p["is_available"],
                        "interval_start": p["start"],
                        "interval_end": p["end"],
                    }
                    for p in prizes
                ],
                "no_prize_probability_bps": 10000
                - sum(p["effective_probability_bps"] for p in prizes),
            }
            expires = None
            if winner and campaign.reward_validity_days is not None:
                try:
                    expires = now + timedelta(days=campaign.reward_validity_days)
                except OverflowError:
                    raise RequestDataError("Reward validity is out of range") from None
            spin = await self.repository.record_spin(
                campaign, customer, key_hash, draw, winner, snapshot, now
            )
            await self.repository.advance_participation(
                participation, day, count + 1, now
            )
            if winner:
                await self.repository.award(spin, winner, expires)
            result = await self._spin_response(spin)
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def rewards(self, principal: Principal, limit=50, offset=0):
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise RequestDataError("Invalid pagination")
        rows = await self.repository.rewards(
            customer_identity(principal), limit, offset
        )
        now = self.clock()
        return [reward_view(row, now) for row in rows]

    async def redeem(self, principal: Principal, branch_id: UUID, reward_id: UUID):
        try:
            actor = await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_REDEEM"
            )
            await self._branch(branch_id, lock=True)
            await require_administration(
                self.authorization, principal, branch_id, "PROMOTION_REDEEM"
            )
            reward = await self.repository.branch_reward(
                branch_id, reward_id, lock=True
            )
            if reward is None:
                raise AdministrationNotFound(
                    "ROULETTE_REWARD_NOT_FOUND", "Reward not found"
                )
            if reward.status == "REDEEMED":
                await self.repository.commit()
                return reward
            if reward_view(reward, self.clock()).status == "EXPIRED":
                raise AdministrationConflict(
                    "ROULETTE_REWARD_EXPIRED", "Reward has expired"
                )
            result = await self.repository.redeem_reward(reward.id, actor, self.clock())
            await self._audit(actor, branch_id, result, "ROULETTE_REWARD_REDEEMED")
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise
