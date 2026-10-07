from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.cancellations.domain.models import (
    CancellationSource,
    ReasonCode,
    RequestStatus,
    plain_text,
)
from app.modules.payments.presentation.refund_schemas import RefundResponse


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and not isinstance(
            value, (RequestStatus, ReasonCode)
        ):
            return plain_text(value, 2000)
        return value


class EmptyRequest(RequestModel):
    pass


class PaginationRequest(RequestModel):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


class RequestListQuery(PaginationRequest):
    status: RequestStatus = RequestStatus.PENDING


class CreateRequest(RequestModel):
    reason: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class ReviewRequest(RequestModel):
    evaluation_note: (
        Annotated[str, StringConstraints(min_length=1, max_length=2000)] | None
    ) = None


class DirectCancelRequest(RequestModel):
    reason_code: Literal["OUT_OF_STOCK", "OTHER"]
    reason: Annotated[str, StringConstraints(min_length=1, max_length=1000)] | None = (
        None
    )

    @model_validator(mode="after")
    def other_requires_reason(self):
        if self.reason_code == "OTHER" and self.reason is None:
            raise ValueError("Reason is required")
        return self


class CustomerRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    reason: str
    status: RequestStatus
    requested_at: datetime
    evaluated_at: datetime | None


class AdminRequestResponse(CustomerRequestResponse):
    customer_id: UUID
    branch_id: UUID
    evaluated_by_user_id: UUID | None
    evaluation_note: str | None


class CancellationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    branch_id: UUID
    cancellation_request_id: UUID | None
    source: CancellationSource
    reason_code: ReasonCode
    reason_text: str | None
    cancelled_by_user_id: UUID
    cancelled_at: datetime


class OutcomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    cancellation: CancellationResponse
    refund: RefundResponse | None
