"""Durable notification facts, not a second Orders state machine."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus

BIGINT_MAX = 9223372036854775807
MAX_PUSH_ATTEMPTS = 5
PUSH_LEASE_SECONDS = 120
MAX_PUSH_TOKEN_BYTES = 2048


class NotificationRuleError(ValueError):
    pass


def aware(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise NotificationRuleError("Timezone-aware time required")


def cursor(value):
    if type(value) is not int or not 0 <= value <= BIGINT_MAX:
        raise NotificationRuleError("Invalid cursor")
    return value


def provider_code(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value):
        raise NotificationRuleError("Invalid provider")
    return value


def push_token(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_PUSH_TOKEN_BYTES
        or any(c.isspace() or unicodedata.category(c).startswith("C") for c in value)
    ):
        raise NotificationRuleError("Invalid opaque push token")
    return value


class NotificationKind(StrEnum):
    ORDER_RECEIVED = "ORDER_RECEIVED"
    ORDER_PREPARING = "ORDER_PREPARING"
    ORDER_READY = "ORDER_READY"
    ORDER_READY_FOR_PICKUP = "ORDER_READY_FOR_PICKUP"
    ORDER_OUT_FOR_DELIVERY = "ORDER_OUT_FOR_DELIVERY"
    ORDER_DELIVERED = "ORDER_DELIVERED"
    DELIVERY_DELAYED = "DELIVERY_DELAYED"


class NotificationSource(StrEnum):
    ORDER = "ORDER"
    ORDER_STATUS_HISTORY = "ORDER_STATUS_HISTORY"
    DELIVERY_DELAY_INCIDENT = "DELIVERY_DELAY_INCIDENT"


class DevicePlatform(StrEnum):
    ANDROID = "ANDROID"
    IOS = "IOS"


class PushDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PushResultKind(StrEnum):
    SENT = "SENT"
    INVALID_TOKEN = "INVALID_TOKEN"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


class RealtimeEventType(StrEnum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_CHANGED = "ORDER_CHANGED"
    DELIVERY_DELAYED = "DELIVERY_DELAYED"


def status_notification(mode, status, from_status):
    if not isinstance(mode, OrderMode) or not isinstance(status, OrderStatus):
        raise NotificationRuleError("Invalid order notification source")
    if from_status is None or from_status == status:
        return None
    if status == OrderStatus.PREPARING:
        return NotificationKind.ORDER_PREPARING
    if status == OrderStatus.READY and mode in {OrderMode.LOCAL, OrderMode.DELIVERY}:
        return NotificationKind.ORDER_READY
    if status == OrderStatus.READY_FOR_PICKUP and mode == OrderMode.PICKUP:
        return NotificationKind.ORDER_READY_FOR_PICKUP
    if status == OrderStatus.OUT_FOR_DELIVERY and mode == OrderMode.DELIVERY:
        return NotificationKind.ORDER_OUT_FOR_DELIVERY
    if status == OrderStatus.DELIVERED and mode == OrderMode.DELIVERY:
        return NotificationKind.ORDER_DELIVERED
    return None


def retry_seconds(attempt_count):
    if type(attempt_count) is not int or not 1 <= attempt_count <= MAX_PUSH_ATTEMPTS:
        raise NotificationRuleError("Invalid attempt count")
    return (30, 120, 600, 1800, 3600)[attempt_count - 1]


@dataclass(frozen=True, kw_only=True, slots=True)
class Notification:
    id: UUID
    sequence_id: int
    customer_id: UUID
    order_id: UUID
    branch_id: UUID
    kind: NotificationKind
    order_number_snapshot: int
    order_status: OrderStatus | None
    source_kind: NotificationSource
    source_id: UUID
    created_at: datetime
    read_at: datetime | None = None

    def __post_init__(self):
        if (
            cursor(self.sequence_id) == 0
            or cursor(self.order_number_snapshot) == 0
            or not isinstance(self.kind, NotificationKind)
            or not isinstance(self.source_kind, NotificationSource)
            or (
                self.order_status is not None
                and not isinstance(self.order_status, OrderStatus)
            )
        ):
            raise NotificationRuleError("Invalid notification")
        expected = (
            NotificationSource.ORDER
            if self.kind == NotificationKind.ORDER_RECEIVED
            else NotificationSource.DELIVERY_DELAY_INCIDENT
            if self.kind == NotificationKind.DELIVERY_DELAYED
            else NotificationSource.ORDER_STATUS_HISTORY
        )
        if self.source_kind != expected or (
            expected == NotificationSource.ORDER and self.source_id != self.order_id
        ):
            raise NotificationRuleError("Invalid notification provenance")
        aware(self.created_at)
        if self.read_at is not None:
            aware(self.read_at)
            if self.read_at < self.created_at:
                raise NotificationRuleError("Read precedes notification")


@dataclass(frozen=True, kw_only=True, slots=True)
class NotificationDevice:
    id: UUID
    installation_id: UUID
    customer_id: UUID
    platform: DevicePlatform
    provider_code: str
    push_token: str = field(repr=False)
    is_active: bool
    generation: int
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    send_locked_until: datetime | None = None

    def __post_init__(self):
        provider_code(self.provider_code)
        push_token(self.push_token)
        if (
            not isinstance(self.platform, DevicePlatform)
            or type(self.is_active) is not bool
            or type(self.generation) is not int
            or not 1 <= self.generation <= 2147483647
        ):
            raise NotificationRuleError("Invalid device")
        for value in (
            self.last_seen_at,
            self.created_at,
            self.updated_at,
            self.send_locked_until,
        ):
            if value is not None:
                aware(value)


@dataclass(frozen=True, kw_only=True, slots=True)
class PushDelivery:
    id: UUID
    notification_id: UUID
    device_id: UUID
    provider_code: str
    device_generation: int
    status: PushDeliveryStatus
    attempt_count: int
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime
    locked_until: datetime | None = None
    claim_token: UUID | None = None
    provider_message_id: str | None = None
    failure_code: str | None = None
    sent_at: datetime | None = None

    def __post_init__(self):
        provider_code(self.provider_code)
        if (
            not isinstance(self.status, PushDeliveryStatus)
            or type(self.attempt_count) is not int
            or not 0 <= self.attempt_count <= MAX_PUSH_ATTEMPTS
            or type(self.device_generation) is not int
            or self.device_generation < 1
        ):
            raise NotificationRuleError("Invalid push delivery")
        processing = self.status == PushDeliveryStatus.PROCESSING
        if (
            processing != (self.locked_until is not None)
            or processing != (self.claim_token is not None)
            or (self.status == PushDeliveryStatus.SENT) != (self.sent_at is not None)
        ):
            raise NotificationRuleError("Invalid delivery state")
        for value in (
            self.next_attempt_at,
            self.created_at,
            self.updated_at,
            self.locked_until,
            self.sent_at,
        ):
            if value is not None:
                aware(value)
        if self.provider_message_id is not None and (
            self.status != PushDeliveryStatus.SENT
            or not 1 <= len(self.provider_message_id) <= 255
            or any(
                unicodedata.category(c).startswith("C")
                for c in self.provider_message_id
            )
        ):
            raise NotificationRuleError("Invalid safe provider message identifier")
        if self.failure_code is not None and not re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,63}", self.failure_code
        ):
            raise NotificationRuleError("Invalid safe delivery failure")


@dataclass(frozen=True, kw_only=True, slots=True)
class RealtimeOrderEvent:
    id: int
    branch_id: UUID
    order_id: UUID
    order_number: int
    mode: OrderMode
    event_type: RealtimeEventType
    status: OrderStatus
    payment_status: PaymentStatus
    status_changed: bool
    payment_status_changed: bool
    occurred_at: datetime
    source_reference_id: UUID | None = None

    def __post_init__(self):
        if (
            cursor(self.id) == 0
            or cursor(self.order_number) == 0
            or not isinstance(self.mode, OrderMode)
            or not isinstance(self.event_type, RealtimeEventType)
            or not isinstance(self.status, OrderStatus)
            or not isinstance(self.payment_status, PaymentStatus)
            or type(self.status_changed) is not bool
            or type(self.payment_status_changed) is not bool
        ):
            raise NotificationRuleError("Invalid realtime fact")
        aware(self.occurred_at)
