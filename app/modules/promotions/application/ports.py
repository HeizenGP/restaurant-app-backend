from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.catalog.application.dtos import PublicProduct
from app.modules.promotions.domain.models import (
    CustomerReward,
    RouletteCampaign,
    RouletteParticipation,
    RoulettePrize,
    RouletteSpin,
)


class SecureRandomPort(Protocol):
    def draw(self) -> int: ...


class PrizeCatalog(Protocol):
    async def products(
        self, branch_id: UUID, product_ids: tuple[UUID, ...]
    ) -> dict[UUID, PublicProduct]: ...


class PromotionRepository(Protocol):
    async def campaigns(
        self, branch_id: UUID, limit: int, offset: int
    ) -> list[RouletteCampaign]: ...
    async def campaign(
        self, branch_id: UUID, campaign_id: UUID, *, lock: bool = False
    ) -> RouletteCampaign | None: ...
    async def active_campaign(
        self, branch_id: UUID, *, lock: bool = False
    ) -> RouletteCampaign | None: ...
    async def create_campaign(
        self, branch_id: UUID, actor: UUID, values: dict
    ) -> RouletteCampaign: ...
    async def change_campaign(
        self, campaign_id: UUID, values: dict
    ) -> RouletteCampaign: ...
    async def prizes(self, campaign_id: UUID) -> list[RoulettePrize]: ...
    async def create_prize(self, campaign_id: UUID, values: dict) -> RoulettePrize: ...
    async def change_prize(self, prize_id: UUID, values: dict) -> RoulettePrize: ...
    async def participation(
        self, campaign_id: UUID, customer_id: UUID, *, lock: bool = False
    ) -> RouletteParticipation | None: ...
    async def find_spin(
        self, branch_id: UUID, customer_id: UUID, key_hash: str
    ) -> RouletteSpin | None: ...
    async def spin_reward(self, spin_id: UUID) -> CustomerReward | None: ...
    async def record_spin(
        self,
        campaign: RouletteCampaign,
        customer_id: UUID,
        key_hash: str,
        draw: int,
        prize: dict | None,
        snapshot: dict,
        now: datetime,
    ) -> RouletteSpin: ...
    async def advance_participation(
        self, participation: RouletteParticipation, day, count: int, now: datetime
    ) -> None: ...
    async def award(
        self, spin: RouletteSpin, prize: dict, expires_at: datetime | None
    ) -> CustomerReward: ...
    async def rewards(
        self, customer_id: UUID, limit: int, offset: int
    ) -> list[CustomerReward]: ...
    async def branch_reward(
        self, branch_id: UUID, reward_id: UUID, *, lock: bool = False
    ) -> CustomerReward | None: ...
    async def redeem_reward(
        self, reward_id: UUID, actor: UUID, now: datetime
    ) -> CustomerReward: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
