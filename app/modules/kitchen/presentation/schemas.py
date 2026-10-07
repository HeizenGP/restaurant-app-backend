from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.orders.domain.models import OrderMode, OrderStatus


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueueRequest(EmptyRequest):
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=100_000)
    mode: OrderMode | None = None
    status: Literal["WAITING", "PREPARING", "READY", "READY_FOR_PICKUP"] | None = None


class KitchenAddonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    addon_name_snapshot: str
    option_name_snapshot: str


class KitchenItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_name_snapshot: str
    presentation_name_snapshot: str
    quantity: int
    notes: str | None
    addon_options: list[KitchenAddonResponse]


class KitchenHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    created_at: datetime


class KitchenTimingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    entered_waiting_at: datetime
    started_preparing_at: datetime | None
    ready_at: datetime | None
    waiting_seconds: int = Field(ge=0)
    preparation_seconds: int = Field(ge=0)
    current_status_seconds: int = Field(ge=0)


class KitchenOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_number: int
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    created_at: datetime
    confirmed_at: datetime
    generated_at: datetime
    table_label: str | None
    requested_pickup_at: datetime | None
    estimated_ready_at: datetime | None
    estimated_delivery_at: datetime | None
    items: list[KitchenItemResponse]
    timing: KitchenTimingResponse


class KitchenOrderDetailResponse(KitchenOrderResponse):
    history: list[KitchenHistoryResponse]


class KitchenQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    generated_at: datetime
    waiting: list[KitchenOrderResponse]
    preparing: list[KitchenOrderResponse]
    ready: list[KitchenOrderResponse]
    limit: int
    offset: int
    has_more: bool
