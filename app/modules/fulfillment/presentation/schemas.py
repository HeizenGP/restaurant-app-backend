from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
)

from app.modules.fulfillment.application.dtos import DeliveryQueueCard
from app.modules.fulfillment.domain.models import DecisionStatus, clean_text
from app.modules.fulfillment.domain.policies import normalized_name, normalized_phone
from app.modules.orders.domain.models import OrderStatus


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def check_text(cls, value):
        if isinstance(value, str):
            return clean_text(value)
        return value


class EmptyRequest(RequestModel):
    pass


class PaginationRequest(RequestModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


class LimitRequest(RequestModel):
    limit: int = Field(default=50, ge=1, le=100)


class DetectionRequest(LimitRequest):
    after_order_number: int = Field(default=0, ge=0, le=9223372036854775807)


class QueueRequest(PaginationRequest):
    status: Literal["WAITING", "PREPARING", "READY", "OUT_FOR_DELIVERY"] | None = None


class IncidentListRequest(PaginationRequest):
    status: DecisionStatus | None = None


class PickupCompleteRequest(RequestModel):
    customer_name: Annotated[str, StringConstraints(min_length=1, max_length=180)]
    customer_phone: Annotated[str, StringConstraints(min_length=1, max_length=40)]

    @field_validator("customer_name")
    @classmethod
    def name_valid(cls, value):
        normalized_name(value)
        return value

    @field_validator("customer_phone")
    @classmethod
    def phone_valid(cls, value):
        normalized_phone(value)
        return value


class AssignmentRequest(RequestModel):
    assigned_user_id: UUID


class RejectRequest(RequestModel):
    customer_responsibility: StrictBool | None = None
    evaluation_note: (
        Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None
    ) = None


class ApproveRequest(RejectRequest):
    remediation_description: Annotated[
        str, StringConstraints(min_length=1, max_length=2000)
    ]


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PickupRecommendationResponse(ResponseModel):
    order_id: UUID
    order_number: int
    requested_pickup_at: datetime
    initial_release_at: datetime
    recommended_release_at: datetime
    initial_estimated_ready_at: datetime
    estimated_ready_at: datetime
    queue_depth: int
    minutes_until_release: int
    is_due: bool


class TransitionResponse(ResponseModel):
    order_id: UUID
    order_number: int
    status: OrderStatus
    changed: bool


class BulkReleaseResponse(ResponseModel):
    evaluated: int
    released: int
    queue_depth: int
    orders: list[TransitionResponse]


class AssignmentResponse(ResponseModel):
    id: UUID
    order_id: UUID
    assigned_user_id: UUID
    assigned_by_user_id: UUID
    assigned_at: datetime
    unassigned_at: datetime | None
    unassigned_by_user_id: UUID | None
    completed_at: datetime | None


class DetectionResponse(ResponseModel):
    evaluated: int
    new_incidents: int
    existing_incidents: int
    next_order_number: int | None


class IncidentResponse(ResponseModel):
    id: UUID
    order_id: UUID
    branch_id: UUID
    committed_eta: datetime
    delay_threshold_seconds: int
    detected_at: datetime
    observed_order_status: OrderStatus
    delay_seconds_at_detection: int
    decision_status: DecisionStatus
    evaluated_by_user_id: UUID | None
    evaluated_at: datetime | None
    customer_responsibility: bool | None
    evaluation_note: str | None
    remediation_description: str | None
    created_at: datetime
    updated_at: datetime


class DeliveryQueueResponse(ResponseModel):
    order_id: UUID
    order_number: int
    status: OrderStatus
    estimated_delivery_at: datetime
    delivery_zone_name_snapshot: str
    recipient_name_snapshot: str
    recipient_phone_snapshot: str
    address_line_snapshot: str
    reference_text_snapshot: str | None
    district_snapshot: str
    city_snapshot: str
    department_snapshot: str
    confirmed_at: datetime
    waiting_at: datetime | None
    preparing_at: datetime | None
    ready_at: datetime | None
    dispatched_at: datetime | None
    delivered_at: datetime | None
    current_delay_seconds: int
    is_delayed: bool
    active_assignment: AssignmentResponse | None

    @classmethod
    def from_card(cls, card: DeliveryQueueCard):
        fields = {
            k: getattr(card.order, k)
            for k in cls.model_fields
            if k
            not in {
                "order_id",
                "active_assignment",
                "current_delay_seconds",
                "is_delayed",
            }
        }
        return cls(
            **fields,
            order_id=card.order.id,
            active_assignment=AssignmentResponse.model_validate(card.active_assignment)
            if card.active_assignment
            else None,
            current_delay_seconds=card.current_delay_seconds,
            is_delayed=card.is_delayed,
        )
