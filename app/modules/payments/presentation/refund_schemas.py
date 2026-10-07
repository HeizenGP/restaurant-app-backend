from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.domain.models import AttemptStatus
from app.modules.payments.domain.refunds import RefundHistorySource, RefundStatus


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefundListQuery(EmptyRequest):
    status: RefundStatus | None = None
    method_type: PaymentMethodType | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=2147483647)


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    amount: Decimal
    currency_code: str
    method_type: PaymentMethodType
    status: RefundStatus
    requested_at: datetime
    refunded_at: datetime | None


class RefundAdminResponse(RefundResponse):
    payment_id: UUID
    reconciliation_required: bool


class RefundAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: AttemptStatus
    amount: Decimal
    created_at: datetime
    completed_at: datetime | None


class RefundHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    from_status: RefundStatus | None
    to_status: RefundStatus
    source: RefundHistorySource
    changed_by_user_id: UUID | None
    created_at: datetime


class RefundDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    refund: RefundAdminResponse
    attempts: list[RefundAttemptResponse]
    history: list[RefundHistoryResponse]


class RefundProcessingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    refund: RefundAdminResponse
    attempt: RefundAttemptResponse


RefundKey = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
]


class RefundWebhookAcknowledgement(BaseModel):
    received: bool = True
