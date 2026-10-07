from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.payments.application.dtos import VerifiedPaymentEvent
from app.modules.payments.domain.models import (
    AttemptStatus,
    PaymentRuleError,
    code,
    provider_code,
    text,
)
from app.modules.payments.domain.refunds import (
    Refund,
    RefundAttempt,
    RefundStatusHistory,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class VerifiedRefundEvent(VerifiedPaymentEvent):
    """Only a trusted refund adapter can produce this internal command."""


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundAttemptRequest:
    refund_id: UUID
    payment_id: UUID
    attempt_id: UUID
    original_provider_reference: str
    amount: Decimal
    currency_code: str
    provider_idempotency_key: str


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundAttemptResult:
    provider_code: str
    provider_reference: str | None
    status: AttemptStatus
    failure_code: str | None = None

    def __post_init__(self):
        provider_code(self.provider_code)
        if not isinstance(self.status, AttemptStatus) or self.status not in {
            AttemptStatus.PROCESSING,
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
        }:
            raise PaymentRuleError("Invalid trusted refund result")
        if self.status != AttemptStatus.FAILED and self.provider_reference is None:
            raise PaymentRuleError("Refund provider reference required")
        if self.provider_reference is not None:
            text(self.provider_reference, 255)
        if self.failure_code is not None:
            code(self.failure_code)
            if self.status != AttemptStatus.FAILED:
                raise PaymentRuleError("Failure requires a failed refund attempt")


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundAttemptLocator:
    refund_id: UUID
    attempt_id: UUID


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundView:
    refund: Refund
    attempts: tuple[RefundAttempt, ...]
    history: tuple[RefundStatusHistory, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundProcessing:
    refund: Refund
    attempt: RefundAttempt
