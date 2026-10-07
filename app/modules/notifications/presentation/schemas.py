from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.modules.notifications.domain.content import content as notification_content
from app.modules.notifications.domain.models import (
    BIGINT_MAX,
    DevicePlatform,
    NotificationKind,
    RealtimeEventType,
    provider_code,
    push_token,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyRequest(RequestModel):
    pass


Cursor = Annotated[int, Field(ge=0, le=BIGINT_MAX)]


class NotificationListQuery(RequestModel):
    limit: int = Field(default=50, ge=1, le=100)
    before_sequence_id: Cursor | None = None


class StreamQuery(RequestModel):
    after_id: Cursor | None = None


class EventsQuery(RequestModel):
    after_id: Cursor = 0
    limit: int = Field(default=100, ge=1, le=200)


class SnapshotQuery(RequestModel):
    status: OrderStatus | None = None
    after_order_number: Cursor = 0
    limit: int = Field(default=100, ge=1, le=200)


class DeviceRequest(RequestModel):
    platform: DevicePlatform
    provider_code: str = Field(min_length=1, max_length=32)
    push_token: str = Field(min_length=1, max_length=2048, repr=False)

    @field_validator("provider_code")
    @classmethod
    def valid_provider(cls, value):
        return provider_code(value)

    @field_validator("push_token")
    @classmethod
    def valid_token(cls, value):
        return push_token(value)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class NotificationResponse(ResponseModel):
    id: UUID
    sequence_id: int
    order_id: UUID
    branch_id: UUID
    kind: NotificationKind
    order_number: int = Field(validation_alias="order_number_snapshot")
    order_status: OrderStatus | None
    created_at: datetime
    read_at: datetime | None

    @computed_field
    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @computed_field
    @property
    def title(self) -> str:
        return notification_content(self.kind, self.order_number).title

    @computed_field
    @property
    def body(self) -> str:
        return notification_content(self.kind, self.order_number).body


class NotificationPageResponse(ResponseModel):
    items: list[NotificationResponse]
    latest_sequence_id: int
    next_before_sequence_id: int | None


class UnreadResponse(ResponseModel):
    unread_count: int


class ReadAllResponse(ResponseModel):
    marked_count: int


class DeviceResponse(ResponseModel):
    id: UUID
    installation_id: UUID
    platform: DevicePlatform
    provider_code: str
    is_active: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class OrderSnapshotResponse(ResponseModel):
    order_id: UUID
    order_number: int
    mode: OrderMode
    status: OrderStatus
    payment_status: PaymentStatus
    customer_name_snapshot: str | None
    created_at: datetime
    confirmed_at: datetime | None
    updated_at: datetime


class SnapshotResponse(ResponseModel):
    orders: list[OrderSnapshotResponse]
    latest_event_id: int
    next_after_order_number: int | None


class RealtimeEventResponse(ResponseModel):
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
