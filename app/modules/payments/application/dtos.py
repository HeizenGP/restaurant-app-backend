from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.payments.domain.models import (
    AttemptStatus,
    ClientAction,
    Payment,
    PaymentAttempt,
    PaymentRuleError,
    VerifiedResult,
    aware,
    code,
    money,
    provider_code,
    text,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class PaymentView:
    payment: Payment
    attempts: tuple[PaymentAttempt, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class OnlineInitiation:
    payment: PaymentView
    attempt: PaymentAttempt
    client_action: ClientAction | None = field(repr=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class GatewayAttemptRequest:
    order_id: UUID
    payment_id: UUID
    attempt_id: UUID
    amount: Decimal
    currency_code: str
    provider_idempotency_key: str


@dataclass(frozen=True, kw_only=True, slots=True)
class GatewayAttemptResult:
    provider_code: str
    provider_reference: str | None
    status: AttemptStatus
    client_action: ClientAction | None = field(default=None, repr=False)
    failure_code: str | None = None

    def __post_init__(self) -> None:
        provider_code(self.provider_code)
        if not isinstance(self.status, AttemptStatus) or self.status not in {
            AttemptStatus.PROCESSING,
            AttemptStatus.FAILED,
        }:
            raise PaymentRuleError("Initiation cannot confirm a payment")
        if self.status == AttemptStatus.PROCESSING and self.provider_reference is None:
            raise PaymentRuleError("Processing provider reference required")
        if self.provider_reference is not None:
            text(self.provider_reference, 255)
        if self.status == AttemptStatus.FAILED and self.client_action is not None:
            raise PaymentRuleError("Failed initiation has no client action")
        if self.failure_code is not None:
            code(self.failure_code)
            if self.status != AttemptStatus.FAILED:
                raise PaymentRuleError("Failure code requires a failed initiation")


@dataclass(frozen=True, kw_only=True, slots=True)
class VerifiedPaymentEvent:
    """Internal only; the gateway authenticates before constructing this DTO."""

    provider_code: str
    provider_event_id: str
    provider_reference: str
    result: VerifiedResult
    amount: Decimal
    currency_code: str
    occurred_at: datetime
    event_type: str | None = None

    def __post_init__(self) -> None:
        provider_code(self.provider_code)
        text(self.provider_event_id, 200)
        text(self.provider_reference, 255)
        money(self.amount)
        text(self.currency_code, 3)
        if not isinstance(self.result, VerifiedResult) or not (
            len(self.currency_code) == 3
            and self.currency_code.isascii()
            and self.currency_code.isalpha()
            and self.currency_code.isupper()
        ):
            raise PaymentRuleError("Invalid verified financial event")
        if self.event_type is not None:
            text(self.event_type, 80)
        aware(self.occurred_at)


@dataclass(frozen=True, kw_only=True, slots=True)
class AttemptLocator:
    attempt_id: UUID
    payment_id: UUID
    order_id: UUID
