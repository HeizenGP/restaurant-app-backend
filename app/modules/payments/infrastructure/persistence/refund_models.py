"""Phase 8 historical records; schema changes belong exclusively to Alembic."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class RefundModel(SQLModel, table=True):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric", name="ck_refunds_amount"
        ),
        CheckConstraint("method_type IN ('CASH','ONLINE')", name="ck_refunds_method"),
        CheckConstraint("currency_code = 'PEN'", name="ck_refunds_currency"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','REFUNDED','FAILED')",
            name="ck_refunds_status",
        ),
        CheckConstraint("reason_code = 'CANCELLATION'", name="ck_refunds_reason"),
        CheckConstraint(
            "(status = 'REFUNDED') = (refunded_at IS NOT NULL)",
            name="ck_refunds_refunded_at",
        ),
        CheckConstraint(
            "refunded_at IS NULL OR refunded_at >= requested_at", name="ck_refunds_time"
        ),
        CheckConstraint(
            "method_type <> 'CASH' OR status IN ('PENDING','REFUNDED')",
            name="ck_refunds_cash_state",
        ),
        UniqueConstraint("payment_id", name="uq_refunds_payment"),
        UniqueConstraint("order_id", name="uq_refunds_order"),
        Index("ix_refunds_queue", "status", "requested_at", "id"),
        Index("ix_refunds_recent", "requested_at", "id"),
        Index("ix_refunds_admin_refunded", "status", "refunded_at", "order_id"),
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
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    amount: Decimal = Field(
        sa_column=Column(Numeric(18, 2, asdecimal=True), nullable=False)
    )
    currency_code: str = Field(
        default="PEN",
        sa_column=Column(String(3), nullable=False, server_default=text("'PEN'")),
    )
    method_type: str = Field(sa_column=Column(String(8), nullable=False))
    status: str = Field(
        default="PENDING",
        sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'")),
    )
    reason_code: str = Field(
        default="CANCELLATION",
        sa_column=Column(
            String(32), nullable=False, server_default=text("'CANCELLATION'")
        ),
    )
    requested_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    refunded_at: datetime | None = Field(
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


class RefundAttemptModel(SQLModel, table=True):
    __tablename__ = "refund_attempts"
    __table_args__ = (
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name="ck_refund_attempts_key",
        ),
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_refund_attempts_provider",
        ),
        CheckConstraint(
            "status IN ('CREATED','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_refund_attempts_status",
        ),
        CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric", name="ck_refund_attempts_amount"
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED')) = (completed_at IS NOT NULL)",
            name="ck_refund_attempts_completed",
        ),
        CheckConstraint(
            "status NOT IN ('PROCESSING','SUCCEEDED') OR provider_reference IS NOT "
            "NULL",
            name="ck_refund_attempts_reference",
        ),
        CheckConstraint(
            "failure_code IS NULL OR (status = 'FAILED' AND failure_code ~ "
            "'^[A-Z][A-Z0-9_]{0,63}$')",
            name="ck_refund_attempts_failure",
        ),
        UniqueConstraint("refund_id", "idempotency_key", name="uq_refund_attempts_key"),
        Index(
            "uq_refund_attempts_active",
            "refund_id",
            unique=True,
            postgresql_where=text("status IN ('CREATED','PROCESSING')"),
        ),
        Index(
            "uq_refund_attempts_provider_reference",
            "provider_code",
            "provider_reference",
            unique=True,
            postgresql_where=text("provider_reference IS NOT NULL"),
        ),
        Index("ix_refund_attempts_history", "refund_id", "created_at", "id"),
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
    refund_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("refunds.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    provider_code: str = Field(sa_column=Column(String(32), nullable=False))
    provider_reference: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    status: str = Field(
        default="CREATED",
        sa_column=Column(String(16), nullable=False, server_default=text("'CREATED'")),
    )
    amount: Decimal = Field(
        sa_column=Column(Numeric(18, 2, asdecimal=True), nullable=False)
    )
    failure_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
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


class RefundProviderEventModel(SQLModel, table=True):
    __tablename__ = "refund_provider_events"
    __table_args__ = (
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_refund_provider_events_provider",
        ),
        CheckConstraint(
            "payload_hash ~ '^[a-f0-9]{64}$'", name="ck_refund_provider_events_hash"
        ),
        CheckConstraint(
            "result IN ('SUCCEEDED','FAILED')", name="ck_refund_provider_events_result"
        ),
        CheckConstraint(
            "processing_status IN ('RECEIVED','PROCESSED','IGNORED','REJECTED')",
            name="ck_refund_provider_events_status",
        ),
        CheckConstraint(
            "(processing_status = 'RECEIVED') = (processed_at IS NULL)",
            name="ck_refund_provider_events_completion",
        ),
        CheckConstraint(
            "reported_amount >= 0 AND reported_amount <> 'NaN'::numeric",
            name="ck_refund_provider_events_amount",
        ),
        CheckConstraint(
            "reported_currency ~ '^[A-Z]{3}$'",
            name="ck_refund_provider_events_currency",
        ),
        CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_refund_provider_events_reason",
        ),
        UniqueConstraint(
            "provider_code", "provider_event_id", name="uq_refund_provider_events_key"
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
    event_type: str | None = Field(
        default=None, sa_column=Column(String(80), nullable=True)
    )
    result: str = Field(sa_column=Column(String(16), nullable=False))
    reported_amount: Decimal = Field(
        sa_column=Column(Numeric(18, 2, asdecimal=True), nullable=False)
    )
    reported_currency: str = Field(sa_column=Column(String(3), nullable=False))
    provider_occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    processing_status: str = Field(
        default="RECEIVED",
        sa_column=Column(String(16), nullable=False, server_default=text("'RECEIVED'")),
    )
    refund_attempt_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("refund_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    reason_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    received_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class RefundStatusHistoryModel(SQLModel, table=True):
    __tablename__ = "refund_status_history"
    __table_args__ = (
        CheckConstraint(
            "to_status IN ('PENDING','PROCESSING','REFUNDED','FAILED') AND "
            "(from_status IS NULL OR from_status IN "
            "('PENDING','PROCESSING','REFUNDED','FAILED'))",
            name="ck_refund_status_history_status",
        ),
        CheckConstraint(
            "source IN ('STAFF','PROVIDER','SYSTEM')",
            name="ck_refund_status_history_source",
        ),
        CheckConstraint(
            "(source = 'STAFF') = (changed_by_user_id IS NOT NULL)",
            name="ck_refund_status_history_actor",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_refund_status_history_transition",
        ),
        CheckConstraint(
            "from_status IS NOT NULL OR (to_status = 'PENDING' AND source = 'SYSTEM')",
            name="ck_refund_status_history_initial",
        ),
        Index("ix_refund_status_history_timeline", "refund_id", "created_at", "id"),
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
    refund_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("refunds.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    refund_attempt_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("refund_attempts.id", ondelete="RESTRICT"),
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
