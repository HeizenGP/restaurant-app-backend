"""Financial metadata; only Alembic creates these tables."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class PaymentModel(SQLModel, table=True):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payments_order"),
        Index("ix_payments_admin_paid", "status", "paid_at", "order_id"),
        CheckConstraint("method_type IN ('CASH','ONLINE')", name="ck_payments_method"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','PAID','FAILED')",
            name="ck_payments_status",
        ),
        CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric", name="ck_payments_amount"
        ),
        CheckConstraint("currency_code = 'PEN'", name="ck_payments_currency"),
        CheckConstraint(
            "(status = 'PAID') = (paid_at IS NOT NULL)", name="ck_payments_paid_at"
        ),
        CheckConstraint(
            "method_type <> 'CASH' OR status IN ('PENDING','PAID')",
            name="ck_payments_cash_state",
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
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    method_type: str = Field(sa_column=Column(String(8), nullable=False))
    amount: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    currency_code: str = Field(
        default="PEN",
        sa_column=Column(String(3), nullable=False, server_default=text("'PEN'")),
    )
    status: str = Field(
        default="PENDING",
        sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'")),
    )
    paid_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reconciliation_required: bool = Field(
        default=False,
        sa_column=Column(Boolean(), nullable=False, server_default=text("false")),
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


class PaymentAttemptModel(SQLModel, table=True):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        UniqueConstraint(
            "payment_id", "idempotency_key", name="uq_payment_attempts_key"
        ),
        Index(
            "uq_payment_attempts_reference",
            "provider_code",
            "provider_reference",
            unique=True,
            postgresql_where=text("provider_reference IS NOT NULL"),
        ),
        Index(
            "uq_payment_attempts_active",
            "payment_id",
            unique=True,
            postgresql_where=text("status IN ('CREATED','PROCESSING')"),
        ),
        Index("ix_payment_attempts_recent", "payment_id", "created_at", "id"),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name="ck_payment_attempts_key",
        ),
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_payment_attempts_provider",
        ),
        CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric",
            name="ck_payment_attempts_amount",
        ),
        CheckConstraint(
            "status IN ('CREATED','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_payment_attempts_status",
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED')) = (completed_at IS NOT NULL)",
            name="ck_payment_attempts_completed",
        ),
        CheckConstraint(
            "status NOT IN ('PROCESSING','SUCCEEDED') "
            "OR provider_reference IS NOT NULL",
            name="ck_payment_attempts_reference_required",
        ),
        CheckConstraint(
            "provider_reference IS NULL OR (length(provider_reference) BETWEEN "
            "1 AND 255 AND provider_reference = btrim(provider_reference))",
            name="ck_payment_attempts_reference",
        ),
        CheckConstraint(
            "failure_code IS NULL OR (status = 'FAILED' AND failure_code ~ "
            "'^[A-Z][A-Z0-9_]{0,63}$')",
            name="ck_payment_attempts_failure",
        ),
        CheckConstraint(
            "(client_action_kind IS NULL AND client_action_value IS NULL) OR "
            "(client_action_kind IS NOT NULL AND client_action_value IS NOT "
            "NULL AND client_action_kind IN ('REDIRECT','SDK_TOKEN') AND "
            "status = 'PROCESSING' AND length(client_action_value) BETWEEN 1 "
            "AND 2048)",
            name="ck_payment_attempts_action",
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
    payment_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    provider_code: str = Field(sa_column=Column(String(32), nullable=False))
    provider_reference: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    amount: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    status: str = Field(
        default="CREATED",
        sa_column=Column(String(16), nullable=False, server_default=text("'CREATED'")),
    )
    failure_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    client_action_kind: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    client_action_value: str | None = Field(
        default=None, sa_column=Column(Text(), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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


class PaymentStatusHistoryModel(SQLModel, table=True):
    __tablename__ = "payment_status_history"
    __table_args__ = (
        Index("ix_payment_status_history_recent", "payment_id", "created_at", "id"),
        CheckConstraint(
            "to_status IN ('PENDING','PROCESSING','PAID','FAILED') AND "
            "(from_status IS NULL OR from_status IN "
            "('PENDING','PROCESSING','PAID','FAILED'))",
            name="ck_payment_status_history_states",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_payment_status_history_change",
        ),
        CheckConstraint(
            "source IN ('CUSTOMER','PROVIDER','STAFF','SYSTEM')",
            name="ck_payment_status_history_source",
        ),
        CheckConstraint(
            "source <> 'STAFF' OR changed_by_user_id IS NOT NULL",
            name="ck_payment_status_history_staff",
        ),
        CheckConstraint(
            "source NOT IN ('PROVIDER','SYSTEM') OR changed_by_user_id IS NULL",
            name="ck_payment_status_history_service_actor",
        ),
        CheckConstraint(
            "from_status IS NOT NULL OR (to_status = 'PENDING' AND source IN "
            "('SYSTEM','CUSTOMER'))",
            name="ck_payment_status_history_initial",
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
    payment_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    payment_attempt_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payment_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    from_status: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    to_status: str = Field(sa_column=Column(String(16), nullable=False))
    source: str = Field(sa_column=Column(String(16), nullable=False))
    changed_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    reason: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    provider_event_id: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class PaymentProviderEventModel(SQLModel, table=True):
    __tablename__ = "payment_provider_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_code", "provider_event_id", name="uq_payment_provider_events_key"
        ),
        Index(
            "ix_payment_provider_events_processing",
            "processing_status",
            "received_at",
            "id",
        ),
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_payment_provider_events_provider",
        ),
        CheckConstraint(
            "length(provider_event_id) BETWEEN 1 AND 200 AND provider_event_id "
            "= btrim(provider_event_id)",
            name="ck_payment_provider_events_id",
        ),
        CheckConstraint(
            "length(provider_reference) BETWEEN 1 AND 255 AND "
            "provider_reference = btrim(provider_reference)",
            name="ck_payment_provider_events_reference",
        ),
        CheckConstraint(
            "payload_hash ~ '^[a-f0-9]{64}$'", name="ck_payment_provider_events_hash"
        ),
        CheckConstraint(
            "result IN ('SUCCEEDED','FAILED')", name="ck_payment_provider_events_result"
        ),
        CheckConstraint(
            "reported_amount >= 0 AND reported_amount <> 'NaN'::numeric",
            name="ck_payment_provider_events_amount",
        ),
        CheckConstraint(
            "reported_currency ~ '^[A-Z]{3}$'",
            name="ck_payment_provider_events_currency",
        ),
        CheckConstraint(
            "processing_status IN ('RECEIVED','PROCESSED','IGNORED','REJECTED')",
            name="ck_payment_provider_events_status",
        ),
        CheckConstraint(
            "(processing_status = 'RECEIVED') = (processed_at IS NULL)",
            name="ck_payment_provider_events_processed",
        ),
        CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_payment_provider_events_reason",
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
    provider_code: str = Field(sa_column=Column(String(32), nullable=False))
    provider_event_id: str = Field(sa_column=Column(String(200), nullable=False))
    provider_reference: str = Field(sa_column=Column(String(255), nullable=False))
    payload_hash: str = Field(sa_column=Column(String(64), nullable=False))
    result: str = Field(sa_column=Column(String(16), nullable=False))
    reported_amount: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    reported_currency: str = Field(sa_column=Column(String(3), nullable=False))
    provider_occurred_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    event_type: str | None = Field(
        default=None, sa_column=Column(String(80), nullable=True)
    )
    processing_status: str = Field(
        default="RECEIVED",
        sa_column=Column(String(16), nullable=False, server_default=text("'RECEIVED'")),
    )
    payment_attempt_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("payment_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    reason_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    received_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
