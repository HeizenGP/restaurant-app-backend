from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.application.dtos import OnlineInitiation, PaymentView
from app.modules.payments.domain.models import AttemptStatus, PaymentStatus


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: AttemptStatus
    amount: Decimal
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    method_type: PaymentMethodType
    status: PaymentStatus
    amount: Decimal
    currency_code: Literal["PEN"]
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime
    attempts: list[AttemptResponse]

    @classmethod
    def from_view(cls, view: PaymentView) -> "PaymentResponse":
        return cls(
            id=view.payment.id,
            order_id=view.payment.order_id,
            method_type=view.payment.method_type,
            status=view.payment.status,
            amount=view.payment.amount,
            currency_code=view.payment.currency_code,
            paid_at=view.payment.paid_at,
            created_at=view.payment.created_at,
            updated_at=view.payment.updated_at,
            attempts=[AttemptResponse.model_validate(a) for a in view.attempts],
        )


class ClientActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    kind: Literal["REDIRECT", "SDK_TOKEN"]
    value: str


class OnlineResponse(BaseModel):
    payment: PaymentResponse
    attempt: AttemptResponse
    client_action: ClientActionResponse | None

    @classmethod
    def from_result(cls, result: OnlineInitiation) -> "OnlineResponse":
        return cls(
            payment=PaymentResponse.from_view(result.payment),
            attempt=AttemptResponse.model_validate(result.attempt),
            client_action=ClientActionResponse.model_validate(result.client_action)
            if result.client_action
            else None,
        )


class WebhookAcknowledgement(BaseModel):
    status: Literal["acknowledged"] = "acknowledged"
