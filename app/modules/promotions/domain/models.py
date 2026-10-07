from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True)
class RouletteCampaign:
    id: UUID
    branch_id: UUID
    name: str
    terms_text: str
    is_active: bool
    starts_at: datetime
    ends_at: datetime | None
    spin_cooldown_seconds: int
    max_spins_per_customer_per_day: int | None
    reward_validity_days: int | None
    version: int
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RoulettePrize:
    id: UUID
    campaign_id: UUID
    product_id: UUID
    display_name: str
    probability_bps: int
    is_active: bool
    max_awards: int | None
    awarded_count: int
    sort_order: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RouletteParticipation:
    id: UUID
    campaign_id: UUID
    customer_id: UUID
    last_spin_at: datetime | None
    day_key: date | None
    spins_today: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RouletteSpin:
    id: UUID
    campaign_id: UUID
    customer_id: UUID
    branch_id: UUID
    idempotency_key: str
    random_draw: int
    outcome: str
    prize_id: UUID | None
    campaign_version: int
    configuration_snapshot: dict
    spun_at: datetime


@dataclass(frozen=True)
class CustomerReward:
    id: UUID
    spin_id: UUID
    campaign_id: UUID
    customer_id: UUID
    branch_id: UUID
    prize_id: UUID
    product_id: UUID
    product_name_snapshot: str
    status: str
    awarded_at: datetime
    expires_at: datetime | None
    redeemed_at: datetime | None
    redeemed_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
