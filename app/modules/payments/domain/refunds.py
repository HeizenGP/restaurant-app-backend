"""Refund financial truth is independent of the original paid ledger."""

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.domain.models import (
    AttemptStatus,
    EventStatus,
    Payment,
    PaymentAttempt,
    PaymentRuleError,
    PaymentStatus,
    ProviderEvent,
    VerifiedResult,
    aware,
    money,
    text,
)
from app.modules.payments.domain.transitions import transition_attempt
from app.shared.domain.time import utc_now


class RefundStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class RefundHistorySource(StrEnum):
    STAFF = "STAFF"
    PROVIDER = "PROVIDER"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True, kw_only=True, slots=True)
class Refund:
    payment_id: UUID
    order_id: UUID
    amount: Decimal
    method_type: PaymentMethodType
    requested_at: datetime
    currency_code: str = "PEN"
    reason_code: str = "CANCELLATION"
    status: RefundStatus = RefundStatus.PENDING
    refunded_at: datetime | None = None
    reconciliation_required: bool = False
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        money(self.amount)
        if (
            not isinstance(self.method_type, PaymentMethodType)
            or not isinstance(self.status, RefundStatus)
            or self.currency_code != "PEN"
            or self.reason_code != "CANCELLATION"
            or (self.status == RefundStatus.REFUNDED) != (self.refunded_at is not None)
            or type(self.reconciliation_required) is not bool
            or (
                self.method_type == PaymentMethodType.CASH
                and self.status not in {RefundStatus.PENDING, RefundStatus.REFUNDED}
            )
        ):
            raise PaymentRuleError("Inconsistent refund")
        for value in (
            self.requested_at,
            self.refunded_at,
            self.created_at,
            self.updated_at,
        ):
            if value is not None:
                aware(value)
        if self.refunded_at is not None and self.refunded_at < self.requested_at:
            raise PaymentRuleError("Refund precedes obligation")


def validate_full_refund(payment: Payment, order_id, total, method) -> None:
    if (
        payment.order_id != order_id
        or payment.status != PaymentStatus.PAID
        or payment.amount != total
        or payment.currency_code != "PEN"
        or payment.method_type != method
    ):
        raise PaymentRuleError("Refund requires a coherent full paid payment")


def transition_refund(refund: Refund, target: RefundStatus, now: datetime) -> Refund:
    aware(now)
    routes = {
        RefundStatus.PENDING: {RefundStatus.PROCESSING},
        RefundStatus.PROCESSING: {RefundStatus.REFUNDED, RefundStatus.FAILED},
        RefundStatus.FAILED: {RefundStatus.PROCESSING},
        RefundStatus.REFUNDED: set(),
    }
    if refund.method_type == PaymentMethodType.CASH:
        routes = {
            RefundStatus.PENDING: {RefundStatus.REFUNDED},
            RefundStatus.REFUNDED: set(),
        }
    if not isinstance(target, RefundStatus) or target not in routes[refund.status]:
        raise PaymentRuleError("Invalid refund transition")
    return replace(
        refund,
        status=target,
        refunded_at=now if target == RefundStatus.REFUNDED else None,
        updated_at=now,
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundAttempt:
    refund_id: UUID
    idempotency_key: str
    provider_code: str
    amount: Decimal
    provider_reference: str | None = None
    status: AttemptStatus = AttemptStatus.CREATED
    failure_code: str | None = None
    completed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        attempt_as_payment(self)


def attempt_as_payment(attempt):
    values = asdict(attempt)
    values["payment_id"] = values.pop("refund_id")
    return PaymentAttempt(**values)


def transition_refund_attempt(
    attempt, target, now, *, verified=False, reference=None, failure=None
):
    changed = transition_attempt(
        attempt_as_payment(attempt),
        target,
        now,
        verified_capture=verified,
        provider_reference=reference,
        failure_code=failure,
    )
    values = asdict(changed)
    values["refund_id"] = values.pop("payment_id")
    values.pop("client_action")
    return RefundAttempt(**values)


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundStatusHistory:
    refund_id: UUID
    from_status: RefundStatus | None
    to_status: RefundStatus
    source: RefundHistorySource
    refund_attempt_id: UUID | None = None
    changed_by_user_id: UUID | None = None
    reason: str | None = None
    provider_event_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        if (
            not isinstance(self.to_status, RefundStatus)
            or not isinstance(self.source, RefundHistorySource)
            or (
                self.from_status is not None
                and not isinstance(self.from_status, RefundStatus)
            )
            or self.from_status == self.to_status
            or (
                self.from_status is None
                and (
                    self.to_status != RefundStatus.PENDING
                    or self.source != RefundHistorySource.SYSTEM
                )
            )
            or (self.source == RefundHistorySource.STAFF)
            != (self.changed_by_user_id is not None)
        ):
            raise PaymentRuleError("Invalid refund history")
        if self.reason is not None:
            text(self.reason, 200)
        if self.provider_event_id is not None:
            text(self.provider_event_id, 200)
        aware(self.created_at)


@dataclass(frozen=True, kw_only=True, slots=True)
class RefundProviderEvent:
    provider_code: str
    provider_event_id: str
    provider_reference: str
    payload_hash: str
    result: VerifiedResult
    reported_amount: Decimal
    reported_currency: str
    provider_occurred_at: datetime
    event_type: str | None = None
    processing_status: EventStatus = EventStatus.RECEIVED
    refund_attempt_id: UUID | None = None
    reason_code: str | None = None
    processed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    received_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        values = asdict(self)
        values["payment_attempt_id"] = values.pop("refund_attempt_id")
        ProviderEvent(**values)
