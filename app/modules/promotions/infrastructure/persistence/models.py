"""Persistence metadata; creation is owned exclusively by Alembic."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class RouletteCampaignModel(SQLModel, table=True):
    __tablename__ = "roulette_campaigns"
    __table_args__ = (
        CheckConstraint(
            "spin_cooldown_seconds>=0 AND (max_spins_per_customer_per_day IS "
            "NULL OR max_spins_per_customer_per_day>=1) AND "
            "(reward_validity_days IS NULL OR reward_validity_days>=1) AND "
            "version>=1",
            name="ck_roulette_campaigns_rules",
        ),
        CheckConstraint(
            "ends_at IS NULL OR ends_at>starts_at", name="ck_roulette_campaigns_window"
        ),
        CheckConstraint(
            "length(btrim(terms_text)) BETWEEN 1 AND 10000 AND length(btrim(name))>0",
            name="ck_roulette_campaigns_terms",
        ),
        Index(
            "uq_roulette_campaigns_active_branch",
            "branch_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index("ix_roulette_campaigns_branch_created", "branch_id", "created_at", "id"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(String(150), nullable=False))
    terms_text: str = Field(sa_column=Column(Text(), nullable=False))
    is_active: bool = Field(
        default=False,
        sa_column=Column(Boolean(), nullable=False, server_default=text("false")),
    )
    starts_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    ends_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    spin_cooldown_seconds: int = Field(
        default=0, sa_column=Column(Integer(), nullable=False, server_default=text("0"))
    )
    max_spins_per_customer_per_day: int | None = Field(
        default=None, sa_column=Column(Integer(), nullable=True)
    )
    reward_validity_days: int | None = Field(
        default=None, sa_column=Column(Integer(), nullable=True)
    )
    version: int = Field(
        default=1, sa_column=Column(Integer(), nullable=False, server_default=text("1"))
    )
    created_by_user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class RoulettePrizeModel(SQLModel, table=True):
    __tablename__ = "roulette_prizes"
    __table_args__ = (
        CheckConstraint(
            "probability_bps BETWEEN 0 AND 10000", name="ck_roulette_prizes_probability"
        ),
        CheckConstraint(
            "awarded_count>=0 AND (max_awards IS NULL OR (max_awards>=0 AND "
            "awarded_count<=max_awards))",
            name="ck_roulette_prizes_awards",
        ),
        CheckConstraint(
            "length(btrim(display_name))>0", name="ck_roulette_prizes_name"
        ),
        Index("ix_roulette_prizes_campaign_sort", "campaign_id", "sort_order", "id"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
    )
    campaign_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    display_name: str = Field(sa_column=Column(String(150), nullable=False))
    probability_bps: int = Field(sa_column=Column(Integer(), nullable=False))
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean(), nullable=False, server_default=text("true")),
    )
    max_awards: int | None = Field(
        default=None, sa_column=Column(Integer(), nullable=True)
    )
    awarded_count: int = Field(
        default=0, sa_column=Column(Integer(), nullable=False, server_default=text("0"))
    )
    sort_order: int = Field(
        default=0, sa_column=Column(Integer(), nullable=False, server_default=text("0"))
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class RouletteParticipationModel(SQLModel, table=True):
    __tablename__ = "roulette_participations"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "customer_id", name="uq_roulette_participations_customer"
        ),
        CheckConstraint("spins_today>=0", name="ck_roulette_participations_count"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
    )
    campaign_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    last_spin_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    day_key: date | None = Field(default=None, sa_column=Column(Date(), nullable=True))
    spins_today: int = Field(
        default=0, sa_column=Column(Integer(), nullable=False, server_default=text("0"))
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class RouletteSpinModel(SQLModel, table=True):
    __tablename__ = "roulette_spins"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "customer_id",
            "idempotency_key",
            name="uq_roulette_spins_campaign_key",
        ),
        UniqueConstraint(
            "branch_id",
            "customer_id",
            "idempotency_key",
            name="uq_roulette_spins_branch_key",
        ),
        CheckConstraint(
            "random_draw BETWEEN 0 AND 9999", name="ck_roulette_spins_draw"
        ),
        CheckConstraint(
            "(outcome='WIN' AND prize_id IS NOT NULL) OR (outcome='NO_PRIZE' "
            "AND prize_id IS NULL)",
            name="ck_roulette_spins_outcome",
        ),
        CheckConstraint("campaign_version>=1", name="ck_roulette_spins_version"),
        CheckConstraint(
            "idempotency_key ~ '^[a-f0-9]{64}$'", name="ck_roulette_spins_key"
        ),
        CheckConstraint(
            "jsonb_typeof(configuration_snapshot)='object'",
            name="ck_roulette_spins_snapshot",
        ),
        Index("ix_roulette_spins_customer_time", "customer_id", "spun_at", "id"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
    )
    campaign_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    idempotency_key: str = Field(sa_column=Column(String(64), nullable=False))
    random_draw: int = Field(sa_column=Column(SmallInteger(), nullable=False))
    outcome: str = Field(sa_column=Column(String(16), nullable=False))
    prize_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_prizes.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    campaign_version: int = Field(sa_column=Column(Integer(), nullable=False))
    configuration_snapshot: dict = Field(sa_column=Column(JSONB(), nullable=False))
    spun_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class CustomerRewardModel(SQLModel, table=True):
    __tablename__ = "customer_rewards"
    __table_args__ = (
        UniqueConstraint("spin_id", name="uq_customer_rewards_spin"),
        CheckConstraint(
            "status IN ('AVAILABLE','REDEEMED','EXPIRED')",
            name="ck_customer_rewards_status",
        ),
        CheckConstraint(
            "(status='REDEEMED' AND redeemed_at IS NOT NULL AND "
            "redeemed_by_user_id IS NOT NULL) OR (status IN "
            "('AVAILABLE','EXPIRED') AND redeemed_at IS NULL AND "
            "redeemed_by_user_id IS NULL)",
            name="ck_customer_rewards_redemption",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at>awarded_at",
            name="ck_customer_rewards_expiry",
        ),
        Index(
            "ix_customer_rewards_customer_status",
            "customer_id",
            "status",
            "awarded_at",
            "id",
        ),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
    )
    spin_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_spins.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    campaign_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_campaigns.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    prize_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("roulette_prizes.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    product_name_snapshot: str = Field(sa_column=Column(String(150), nullable=False))
    status: str = Field(
        default="AVAILABLE",
        sa_column=Column(
            String(16), nullable=False, server_default=text("'AVAILABLE'")
        ),
    )
    awarded_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    redeemed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    redeemed_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
