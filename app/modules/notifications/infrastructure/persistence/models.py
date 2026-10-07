"""Phase 9 projections/outbox. All DDL lives in pinned Alembic revisions."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class RealtimeOrderEventModel(SQLModel, table=True):
    __tablename__ = "realtime_order_events"
    __table_args__ = (
        CheckConstraint(
            "id > 0 AND order_number > 0", name="ck_realtime_order_events_numbers"
        ),
        CheckConstraint(
            "mode IN ('LOCAL','PICKUP','DELIVERY')",
            name="ck_realtime_order_events_mode",
        ),
        CheckConstraint(
            "event_type IN ('ORDER_CREATED','ORDER_CHANGED','DELIVERY_DELAYED')",
            name="ck_realtime_order_events_type",
        ),
        CheckConstraint(
            "status IN ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION','SCHEDULED','WA"
            "ITING','PREPARING','READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY','SERVED"
            "','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_realtime_order_events_status",
        ),
        CheckConstraint(
            "payment_status IN ('PENDING','PAID')",
            name="ck_realtime_order_events_payment",
        ),
        CheckConstraint(
            "event_type <> 'ORDER_CHANGED' OR status_changed OR payment_status_changed",
            name="ck_realtime_order_events_change",
        ),
        CheckConstraint(
            "event_type <> 'DELIVERY_DELAYED' OR (mode = 'DELIVERY' AND source_refere"
            "nce_id IS NOT NULL)",
            name="ck_realtime_order_events_delay",
        ),
        Index("ix_realtime_order_events_branch", "branch_id", "id"),
        Index("ix_realtime_order_events_order", "order_id", "id"),
    )
    id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger(), Identity(always=True), primary_key=True, nullable=False
        ),
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
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
    order_number: int = Field(sa_column=Column(BigInteger(), nullable=False))
    mode: str = Field(sa_column=Column(String(8), nullable=False))
    event_type: str = Field(sa_column=Column(String(24), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False))
    payment_status: str = Field(sa_column=Column(String(8), nullable=False))
    status_changed: bool = Field(sa_column=Column(Boolean(), nullable=False))
    payment_status_changed: bool = Field(sa_column=Column(Boolean(), nullable=False))
    source_reference_id: UUID | None = Field(
        default=None, sa_column=Column(PG_UUID(as_uuid=True), nullable=True)
    )
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class CustomerNotificationModel(SQLModel, table=True):
    __tablename__ = "customer_notifications"
    __table_args__ = (
        CheckConstraint(
            "sequence_id > 0 AND order_number_snapshot > 0",
            name="ck_customer_notifications_numbers",
        ),
        CheckConstraint(
            "kind IN ('ORDER_RECEIVED','ORDER_PREPARING','ORDER_READY','ORDER_READY_F"
            "OR_PICKUP','ORDER_OUT_FOR_DELIVERY','ORDER_DELIVERED','DELIVERY_DELAYED'"
            ")",
            name="ck_customer_notifications_kind",
        ),
        CheckConstraint(
            "order_status IS NULL OR order_status IN ('PENDING_PAYMENT','PENDING_CASH"
            "_CONFIRMATION','SCHEDULED','WAITING','PREPARING','READY','READY_FOR_PICK"
            "UP','OUT_FOR_DELIVERY','SERVED','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_customer_notifications_status",
        ),
        CheckConstraint(
            "(kind = 'ORDER_RECEIVED' AND source_kind = 'ORDER' AND source_id = order"
            "_id) OR (kind = 'DELIVERY_DELAYED' AND source_kind = 'DELIVERY_DELAY_INC"
            "IDENT') OR (kind NOT IN ('ORDER_RECEIVED','DELIVERY_DELAYED') AND source"
            "_kind = 'ORDER_STATUS_HISTORY')",
            name="ck_customer_notifications_source",
        ),
        CheckConstraint(
            "read_at IS NULL OR read_at >= created_at",
            name="ck_customer_notifications_read",
        ),
        UniqueConstraint("sequence_id", name="uq_customer_notifications_sequence"),
        UniqueConstraint(
            "source_kind", "source_id", "kind", name="uq_customer_notifications_source"
        ),
        Index(
            "ix_customer_notifications_history", "customer_id", text("sequence_id DESC")
        ),
        Index("ix_customer_notifications_unread", "customer_id", "read_at"),
        Index("ix_customer_notifications_order", "order_id", "created_at"),
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
    sequence_id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger(), Identity(always=True), nullable=False),
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="RESTRICT"),
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
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    kind: str = Field(sa_column=Column(String(32), nullable=False))
    order_number_snapshot: int = Field(sa_column=Column(BigInteger(), nullable=False))
    order_status: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    source_kind: str = Field(sa_column=Column(String(32), nullable=False))
    source_id: UUID = Field(sa_column=Column(PG_UUID(as_uuid=True), nullable=False))
    read_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class NotificationDeviceModel(SQLModel, table=True):
    __tablename__ = "notification_devices"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('ANDROID','IOS')", name="ck_notification_devices_platform"
        ),
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_notification_devices_provider",
        ),
        CheckConstraint(
            "octet_length(push_token) BETWEEN 1 AND 2048 AND push_token !~ '[[:space:"
            "][:cntrl:]]'",
            name="ck_notification_devices_token",
        ),
        CheckConstraint("generation >= 1", name="ck_notification_devices_generation"),
        UniqueConstraint(
            "installation_id", name="uq_notification_devices_installation"
        ),
        UniqueConstraint(
            "provider_code", "push_token", name="uq_notification_devices_token"
        ),
        Index("ix_notification_devices_owner", "customer_id", "is_active"),
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
    installation_id: UUID = Field(
        sa_column=Column(PG_UUID(as_uuid=True), nullable=False)
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    platform: str = Field(sa_column=Column(String(8), nullable=False))
    provider_code: str = Field(sa_column=Column(String(32), nullable=False))
    push_token: str = Field(repr=False, sa_column=Column(Text(), nullable=False))
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean(), nullable=False, server_default=text("true")),
    )
    generation: int = Field(
        default=1, sa_column=Column(Integer(), nullable=False, server_default=text("1"))
    )
    send_locked_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    last_seen_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
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


class NotificationPushDeliveryModel(SQLModel, table=True):
    __tablename__ = "notification_push_deliveries"
    __table_args__ = (
        CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_notification_push_deliveries_provider",
        ),
        CheckConstraint(
            "device_generation >= 1", name="ck_notification_push_deliveries_generation"
        ),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SENT','FAILED','CANCELLED')",
            name="ck_notification_push_deliveries_status",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 5",
            name="ck_notification_push_deliveries_attempts",
        ),
        CheckConstraint(
            "(status = 'SENT') = (sent_at IS NOT NULL)",
            name="ck_notification_push_deliveries_sent",
        ),
        CheckConstraint(
            "(status = 'PROCESSING') = (locked_until IS NOT NULL) AND (status = 'PROC"
            "ESSING') = (claim_token IS NOT NULL)",
            name="ck_notification_push_deliveries_lease",
        ),
        CheckConstraint(
            "provider_message_id IS NULL OR (status = 'SENT' AND length(provider_mess"
            "age_id) BETWEEN 1 AND 255 AND provider_message_id !~ '[[:cntrl:]]')",
            name="ck_notification_push_deliveries_message",
        ),
        CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_notification_push_deliveries_failure",
        ),
        UniqueConstraint(
            "notification_id", "device_id", name="uq_notification_push_deliveries_pair"
        ),
        Index(
            "ix_notification_push_deliveries_due",
            "status",
            "next_attempt_at",
            "id",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "ix_notification_push_deliveries_reclaim",
            "locked_until",
            "id",
            postgresql_where=text("status = 'PROCESSING'"),
        ),
        Index("ix_notification_push_deliveries_device", "device_id", "status"),
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
    notification_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customer_notifications.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    device_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("notification_devices.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    provider_code: str = Field(sa_column=Column(String(32), nullable=False))
    device_generation: int = Field(sa_column=Column(Integer(), nullable=False))
    status: str = Field(
        default="PENDING",
        sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'")),
    )
    attempt_count: int = Field(
        default=0, sa_column=Column(Integer(), nullable=False, server_default=text("0"))
    )
    next_attempt_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    locked_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    claim_token: UUID | None = Field(
        default=None, sa_column=Column(PG_UUID(as_uuid=True), nullable=True)
    )
    provider_message_id: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    failure_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    sent_at: datetime | None = Field(
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
