from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class RouletteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: UUID


class SpinRequest(RouletteQuery):
    pass


class CreateCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=150)
    terms_text: str = Field(min_length=1, max_length=10000)
    starts_at: datetime
    ends_at: datetime | None = None
    spin_cooldown_seconds: int = Field(ge=0, le=2147483647, strict=True)
    max_spins_per_customer_per_day: int | None = Field(
        default=None, ge=1, le=2147483647, strict=True
    )
    reward_validity_days: int | None = Field(
        default=None, ge=1, le=2147483647, strict=True
    )
    is_active: Literal[False] = False


class PatchCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    terms_text: str | None = Field(default=None, min_length=1, max_length=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    spin_cooldown_seconds: int | None = Field(
        default=None, ge=0, le=2147483647, strict=True
    )
    max_spins_per_customer_per_day: int | None = Field(
        default=None, ge=1, le=2147483647, strict=True
    )
    reward_validity_days: int | None = Field(
        default=None, ge=1, le=2147483647, strict=True
    )
    is_active: bool | None = None

    @model_validator(mode="after")
    def fields(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None
            for key in self.model_fields_set
            - {"ends_at", "max_spins_per_customer_per_day", "reward_validity_days"}
        ):
            raise ValueError("Provide non-null configuration fields")
        return self


class CreatePrize(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_id: UUID
    display_name: str = Field(min_length=1, max_length=150)
    probability_bps: int = Field(ge=0, le=10000, strict=True)
    is_active: bool = True
    max_awards: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    sort_order: int = Field(default=0, ge=0, le=2147483647, strict=True)


class PatchPrize(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    product_id: UUID | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    probability_bps: int | None = Field(default=None, ge=0, le=10000, strict=True)
    is_active: bool | None = None
    max_awards: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    sort_order: int | None = Field(default=None, ge=0, le=2147483647, strict=True)

    @model_validator(mode="after")
    def fields(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set - {"max_awards"}
        ):
            raise ValueError("Provide non-null prize fields")
        return self


class PrizeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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
    created_at: datetime
    updated_at: datetime


class CampaignDetail(CampaignResponse):
    prizes: list[PrizeResponse]


class RewardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    spin_id: UUID
    campaign_id: UUID
    branch_id: UUID
    prize_id: UUID
    product_id: UUID
    product_name_snapshot: str
    status: Literal["AVAILABLE", "REDEEMED", "EXPIRED"]
    awarded_at: datetime
    expires_at: datetime | None
    redeemed_at: datetime | None


class PublicPrize(BaseModel):
    id: UUID
    product_id: UUID
    display_name: str
    probability_bps: int
    probability_percent: Decimal
    effective_probability_bps: int
    effective_probability_percent: Decimal
    is_available: bool


class RouletteResponse(BaseModel):
    campaign_id: UUID
    name: str
    terms_text: str
    version: int
    starts_at: datetime
    ends_at: datetime | None
    spin_cooldown_seconds: int
    max_spins_per_customer_per_day: int | None
    reward_validity_days: int | None
    timezone: str
    next_spin_at: datetime | None
    can_spin: bool
    prizes: list[PublicPrize]
    no_prize_probability_bps: int
    no_prize_probability_percent: Decimal


class WonPrizeResponse(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str


class SpinResponse(BaseModel):
    spin_id: UUID
    outcome: Literal["WIN", "NO_PRIZE"]
    campaign_id: UUID
    campaign_version: int
    spun_at: datetime
    prize: WonPrizeResponse | None
    reward: RewardResponse | None
