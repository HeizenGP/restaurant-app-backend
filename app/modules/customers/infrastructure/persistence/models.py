from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CustomerModel(SQLModel, table=True):
    __tablename__ = "customers"
    # Administrative provenance is not an identity field. Its owning adapter
    # projects/writes it explicitly; ordinary Auth/checkout mappings stay stable.
    __mapper_args__ = {"exclude_properties": ["created_by_branch_id"]}
    __table_args__ = (
        Column(
            "created_by_branch_id",
            PG_UUID(as_uuid=True),
            ForeignKey(
                "branches.id", ondelete="RESTRICT", name="fk_customers_admin_origin"
            ),
            nullable=True,
        ),
        CheckConstraint(
            "phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_customers_phone_format",
        ),
        UniqueConstraint("user_id", name="uq_customers_user_id"),
        UniqueConstraint("phone", name="uq_customers_phone"),
        Index("ix_customers_email", "email"),
        Index("ix_customers_admin_origin", "created_by_branch_id", "created_at", "id"),
        Index(
            "ix_customers_admin_name_prefix", text("lower(full_name) text_pattern_ops")
        ),
        Index(
            "ix_customers_admin_email_prefix",
            text("lower(email::text) text_pattern_ops"),
        ),
        Index(
            "ix_customers_admin_phone_prefix",
            "phone",
            postgresql_ops={"phone": "varchar_pattern_ops"},
        ),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
        ),
    )
    full_name: str = Field(sa_column=Column(String(180), nullable=False))
    phone: str = Field(sa_column=Column(String(20), nullable=False))
    email: str | None = Field(default=None, sa_column=Column(CITEXT()))
    phone_verified_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    is_guest: bool | None = Field(
        default=None,
        sa_column=Column(
            Boolean,
            Computed("(user_id IS NULL)", persisted=True),
            nullable=False,
        ),
    )


class OtpChallengeModel(SQLModel, table=True):
    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint(
            "phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_otp_challenges_phone_format",
        ),
        CheckConstraint(
            "purpose IN ('GUEST_ACCESS', 'REGISTER', 'LOGIN', 'PHONE_VERIFY')",
            name="ck_otp_challenges_purpose",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_otp_challenges_attempts_nonnegative",
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="ck_otp_challenges_max_attempts_positive",
        ),
        CheckConstraint(
            "attempts <= max_attempts",
            name="ck_otp_challenges_attempts_within_limit",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_otp_challenges_expiry",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_otp_challenges_consumption_time",
        ),
        Index(
            "ix_otp_challenges_phone_purpose_created_at",
            "phone",
            "purpose",
            "created_at",
        ),
        Index("ix_otp_challenges_customer_id", "customer_id"),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    customer_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="SET NULL"),
        ),
    )
    phone: str = Field(sa_column=Column(String(20), nullable=False))
    purpose: str = Field(sa_column=Column(String(24), nullable=False))
    code_hash: str = Field(sa_column=Column(Text, nullable=False))
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    consumed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    attempts: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    max_attempts: int = Field(
        default=5,
        sa_column=Column(Integer, nullable=False, server_default=text("5")),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


class CustomerAddressModel(SQLModel, table=True):
    __tablename__ = "customer_addresses"
    __table_args__ = (
        CheckConstraint(
            "recipient_phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_customer_addresses_phone_format",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_customer_addresses_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_customer_addresses_longitude",
        ),
        Index("ix_customer_addresses_customer_id", "customer_id"),
        Index(
            "uq_customer_addresses_one_default",
            "customer_id",
            unique=True,
            postgresql_where=text("is_default IS TRUE"),
        ),
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    label: str = Field(sa_column=Column(String(80), nullable=False))
    recipient_name: str = Field(sa_column=Column(String(180), nullable=False))
    recipient_phone: str = Field(sa_column=Column(String(20), nullable=False))
    address_line: str = Field(sa_column=Column(Text, nullable=False))
    reference_text: str | None = Field(default=None, sa_column=Column(Text))
    district: str = Field(sa_column=Column(String(120), nullable=False))
    city: str = Field(
        default="Tarapoto",
        sa_column=Column(
            String(120),
            nullable=False,
            server_default=text("'Tarapoto'"),
        ),
    )
    department: str = Field(
        default="San Martín",
        sa_column=Column(
            String(120),
            nullable=False,
            server_default=text("'San Martín'"),
        ),
    )
    latitude: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(9, 6)),
    )
    longitude: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(10, 7)),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
