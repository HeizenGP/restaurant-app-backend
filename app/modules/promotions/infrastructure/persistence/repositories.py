import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.promotions.domain.models import (
    CustomerReward,
    RouletteCampaign,
    RouletteParticipation,
    RoulettePrize,
    RouletteSpin,
)
from app.shared.application.administration import AdministrationConflict


class SQLAlchemyPromotionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def campaigns(self, branch_id, limit, offset):
        rows = await self.session.execute(
            text(
                "SELECT * FROM roulette_campaigns WHERE branch_id=:branch ORDER "
                "BY created_at DESC,id DESC LIMIT :limit OFFSET :offset"
            ),
            {"branch": branch_id, "limit": limit, "offset": offset},
        )
        return [RouletteCampaign(**row) for row in rows.mappings()]

    async def campaign(self, branch_id, campaign_id, *, lock=False):
        rows = await self.session.execute(
            text(
                "SELECT * FROM roulette_campaigns WHERE branch_id=:branch AND id=:id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"branch": branch_id, "id": campaign_id},
        )
        row = rows.mappings().one_or_none()
        return RouletteCampaign(**row) if row else None

    async def active_campaign(self, branch_id, *, lock=False):
        rows = await self.session.execute(
            text(
                "SELECT * FROM roulette_campaigns WHERE branch_id=:branch AND "
                "is_active IS TRUE" + (" FOR UPDATE" if lock else "")
            ),
            {"branch": branch_id},
        )
        row = rows.mappings().one_or_none()
        return RouletteCampaign(**row) if row else None

    async def create_campaign(self, branch_id, actor, values):
        keys = list(values)
        row = await self.session.execute(
            text(
                "INSERT INTO roulette_campaigns(branch_id,created_by_user_id,"
                + ",".join(keys)
                + ") VALUES (:branch,:actor,"
                + ",".join(":" + k for k in keys)
                + ") RETURNING *"
            ),
            {**values, "branch": branch_id, "actor": actor},
        )
        return RouletteCampaign(**row.mappings().one())

    async def change_campaign(self, campaign_id, values):
        setters = ",".join(k + "=:" + k for k in values)
        try:
            rows = await self.session.execute(
                text(
                    "UPDATE roulette_campaigns SET "
                    + (setters + "," if setters else "")
                    + "version=version+1 WHERE id=:id RETURNING *"
                ),
                {**values, "id": campaign_id},
            )
        except IntegrityError:
            raise AdministrationConflict(
                "ROULETTE_ACTIVE_CAMPAIGN_EXISTS",
                "Another campaign is active in this branch",
            ) from None
        return RouletteCampaign(**rows.mappings().one())

    async def prizes(self, campaign_id):
        rows = await self.session.execute(
            text(
                "SELECT * FROM roulette_prizes WHERE campaign_id=:id ORDER BY "
                "sort_order,id"
            ),
            {"id": campaign_id},
        )
        return [RoulettePrize(**row) for row in rows.mappings()]

    async def create_prize(self, campaign_id, values):
        keys = list(values)
        rows = await self.session.execute(
            text(
                "INSERT INTO roulette_prizes(campaign_id,"
                + ",".join(keys)
                + ") VALUES (:campaign,"
                + ",".join(":" + k for k in keys)
                + ") RETURNING *"
            ),
            {**values, "campaign": campaign_id},
        )
        return RoulettePrize(**rows.mappings().one())

    async def change_prize(self, prize_id, values):
        rows = await self.session.execute(
            text(
                "UPDATE roulette_prizes SET "
                + ",".join(k + "=:" + k for k in values)
                + " WHERE id=:id RETURNING *"
            ),
            {**values, "id": prize_id},
        )
        return RoulettePrize(**rows.mappings().one())

    async def participation(self, campaign_id, customer_id, *, lock=False):
        params = {"campaign": campaign_id, "customer": customer_id}
        if lock:
            await self.session.execute(
                text(
                    "INSERT INTO roulette_participations(campaign_id,"
                    "customer_id) VALUES (:campaign,:customer) "
                    "ON CONFLICT(campaign_id,customer_id) DO NOTHING"
                ),
                params,
            )
        rows = await self.session.execute(
            text(
                "SELECT * FROM roulette_participations WHERE "
                "campaign_id=:campaign AND customer_id=:customer"
                + (" FOR UPDATE" if lock else "")
            ),
            params,
        )
        row = rows.mappings().one_or_none()
        return RouletteParticipation(**row) if row else None

    async def find_spin(self, branch_id, customer_id, key_hash):
        rows = await self.session.execute(
            text(
                "SELECT * FROM roulette_spins WHERE branch_id=:branch AND "
                "customer_id=:customer AND idempotency_key=:key"
            ),
            {"branch": branch_id, "customer": customer_id, "key": key_hash},
        )
        row = rows.mappings().one_or_none()
        return RouletteSpin(**row) if row else None

    async def spin_reward(self, spin_id):
        rows = await self.session.execute(
            text("SELECT * FROM customer_rewards WHERE spin_id=:id"), {"id": spin_id}
        )
        row = rows.mappings().one_or_none()
        return CustomerReward(**row) if row else None

    async def record_spin(
        self, campaign, customer_id, key_hash, draw, prize, snapshot, now
    ):
        rows = await self.session.execute(
            text(
                "INSERT INTO roulette_spins(campaign_id,customer_id,branch_id,"
                "idempotency_key,random_draw,outcome,"
                "prize_id,campaign_version,configuration_snapshot,spun_at) "
                "VALUES (:campaign,:customer,:branch,:key,:draw,:outcome,:prize,"
                ":version,CAST(:snapshot AS jsonb),:now) RETURNING *"
            ),
            {
                "campaign": campaign.id,
                "customer": customer_id,
                "branch": campaign.branch_id,
                "key": key_hash,
                "draw": draw,
                "outcome": "WIN" if prize else "NO_PRIZE",
                "prize": prize["id"] if prize else None,
                "version": campaign.version,
                "snapshot": json.dumps(snapshot, sort_keys=True),
                "now": now,
            },
        )
        return RouletteSpin(**rows.mappings().one())

    async def advance_participation(self, participation, day, count, now):
        await self.session.execute(
            text(
                "UPDATE roulette_participations SET "
                "day_key=:day,spins_today=:count,last_spin_at=:now WHERE id=:id"
            ),
            {"id": participation.id, "day": day, "count": count, "now": now},
        )

    async def award(self, spin, prize, expires_at):
        id_ = await self.session.scalar(
            text(
                "UPDATE roulette_prizes SET awarded_count=awarded_count+1 WHERE "
                "id=:id AND is_active "
                "AND (max_awards IS NULL OR awarded_count<max_awards) RETURNING id"
            ),
            {"id": prize["id"]},
        )
        if id_ is None:
            raise AdministrationConflict(
                "ROULETTE_PRIZE_UNAVAILABLE", "Prize award limit reached"
            )
        rows = await self.session.execute(
            text(
                "INSERT INTO customer_rewards(spin_id,campaign_id,customer_id,"
                "branch_id,prize_id,product_id,"
                "product_name_snapshot,awarded_at,expires_at) "
                "VALUES (:spin,:campaign,:customer,:branch,:prize,:product,"
                ":name,:now,:expires) RETURNING *"
            ),
            {
                "spin": spin.id,
                "campaign": spin.campaign_id,
                "customer": spin.customer_id,
                "branch": spin.branch_id,
                "prize": prize["id"],
                "product": prize["product_id"],
                "name": prize["product_name"],
                "now": spin.spun_at,
                "expires": expires_at,
            },
        )
        return CustomerReward(**rows.mappings().one())

    async def rewards(self, customer_id, limit, offset):
        rows = await self.session.execute(
            text(
                "SELECT * FROM customer_rewards WHERE customer_id=:customer "
                "ORDER BY awarded_at DESC,id DESC LIMIT :limit OFFSET :offset"
            ),
            {"customer": customer_id, "limit": limit, "offset": offset},
        )
        return [CustomerReward(**row) for row in rows.mappings()]

    async def branch_reward(self, branch_id, reward_id, *, lock=False):
        rows = await self.session.execute(
            text(
                "SELECT * FROM customer_rewards WHERE branch_id=:branch AND id=:id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"branch": branch_id, "id": reward_id},
        )
        row = rows.mappings().one_or_none()
        return CustomerReward(**row) if row else None

    async def redeem_reward(self, reward_id, actor, now):
        rows = await self.session.execute(
            text(
                "UPDATE customer_rewards SET "
                "status='REDEEMED',redeemed_at=:now,redeemed_by_user_id=:actor "
                "WHERE id=:id AND status='AVAILABLE' RETURNING *"
            ),
            {"id": reward_id, "actor": actor, "now": now},
        )
        return CustomerReward(**rows.mappings().one())

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
