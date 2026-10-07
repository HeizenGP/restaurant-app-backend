from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.notifications.domain.models import (
    Notification,
    NotificationDevice,
    PushDelivery,
    PushResultKind,
    RealtimeOrderEvent,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus


@dataclass(frozen=True, kw_only=True, slots=True)
class NotificationPage:
    items: tuple[Notification, ...]
    latest_sequence_id: int
    next_before_sequence_id: int | None


@dataclass(frozen=True, kw_only=True, slots=True)
class AdminOrderSnapshot:
    order_id: UUID
    order_number: int
    mode: OrderMode
    status: OrderStatus
    payment_status: PaymentStatus
    customer_name_snapshot: str | None
    created_at: datetime
    confirmed_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, kw_only=True, slots=True)
class AdminSnapshot:
    orders: tuple[AdminOrderSnapshot, ...]
    latest_event_id: int
    next_after_order_number: int | None


@dataclass(frozen=True, kw_only=True, slots=True)
class PushMessage:
    delivery_id: UUID
    notification_id: UUID
    token: str = field(repr=False)
    title: str
    body: str
    data: dict[str, str]
    provider_idempotency_key: str


@dataclass(frozen=True, kw_only=True, slots=True)
class PushResult:
    kind: PushResultKind
    provider_message_id: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class PushClaim:
    delivery: PushDelivery
    device: NotificationDevice = field(repr=False)
    notification: Notification


@dataclass(frozen=True, kw_only=True, slots=True)
class DispatchResult:
    claimed: int
    sent: int
    failed: int
    pending: int
    cancelled_or_stale: int


@dataclass(frozen=True, kw_only=True, slots=True)
class StreamScope:
    principal: Principal
    credential: str = field(repr=False)
    branch_id: UUID | None = None
    permission: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class StreamBatch:
    items: tuple[Notification | RealtimeOrderEvent, ...]
    latest_id: int
    expires_at: datetime | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class StreamFrame:
    event: str | None = None
    id: int | None = None
    data: Notification | RealtimeOrderEvent | dict | None = None
    comment: str | None = None
