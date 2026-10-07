"""Financial domain. Only verified infrastructure or authorized staff confirms money."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID, uuid4

from app.modules.orders.domain.models import PaymentMethodType
from app.shared.domain.time import utc_now

BUSINESS_CURRENCY = "PEN"
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")


class PaymentRuleError(ValueError):
    pass


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"


class AttemptStatus(StrEnum):
    CREATED = "CREATED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class HistorySource(StrEnum):
    CUSTOMER = "CUSTOMER"
    PROVIDER = "PROVIDER"
    STAFF = "STAFF"
    SYSTEM = "SYSTEM"


class EventStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"


class VerifiedResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


ACTIVE_ATTEMPT_STATUSES = (AttemptStatus.CREATED, AttemptStatus.PROCESSING)


def money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise PaymentRuleError("Amount must be a finite Decimal")
    if value < 0 or value > MAX_AMOUNT:
        raise PaymentRuleError("Invalid payment amount")
    try:
        normalized = value.quantize(CENT)
    except InvalidOperation:
        raise PaymentRuleError("Invalid payment precision") from None
    if value != normalized:
        raise PaymentRuleError("Payment amount must have exact cents")
    return normalized


def aware(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PaymentRuleError("Timezone-aware timestamp required")


def text(value: str, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise PaymentRuleError("Invalid payment reference")


def code(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value):
        raise PaymentRuleError("Invalid safe failure code")


def provider_code(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", value):
        raise PaymentRuleError("Invalid provider code")


def idempotency_key(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
        raise PaymentRuleError("Invalid payment idempotency key")


@dataclass(frozen=True, kw_only=True, slots=True)
class ClientAction:
    kind: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.kind not in {"REDIRECT", "SDK_TOKEN"}:
            raise PaymentRuleError("Unsupported client action")
        text(self.value, 2048)
        if self.kind == "REDIRECT":
            from urllib.parse import urlsplit

            parsed = urlsplit(self.value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise PaymentRuleError("Client redirect must be public HTTPS")


@dataclass(frozen=True, kw_only=True, slots=True)
class Payment:
    order_id: UUID
    method_type: PaymentMethodType
    amount: Decimal
    currency_code: str = BUSINESS_CURRENCY
    status: PaymentStatus = PaymentStatus.PENDING
    paid_at: datetime | None = None
    reconciliation_required: bool = False
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        money(self.amount)
        if (
            not isinstance(self.method_type, PaymentMethodType)
            or not isinstance(self.status, PaymentStatus)
            or self.currency_code != BUSINESS_CURRENCY
            or type(self.reconciliation_required) is not bool
            or (self.status == PaymentStatus.PAID) != (self.paid_at is not None)
            or (
                self.method_type == PaymentMethodType.CASH
                and self.status not in {PaymentStatus.PENDING, PaymentStatus.PAID}
            )
        ):
            raise PaymentRuleError("Inconsistent payment state")
        for timestamp in (self.created_at, self.updated_at, self.paid_at):
            if timestamp is not None:
                aware(timestamp)


@dataclass(frozen=True, kw_only=True, slots=True)
class PaymentAttempt:
    payment_id: UUID
    idempotency_key: str
    provider_code: str
    amount: Decimal
    provider_reference: str | None = None
    status: AttemptStatus = AttemptStatus.CREATED
    failure_code: str | None = None
    client_action: ClientAction | None = field(default=None, repr=False)
    completed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        money(self.amount)
        idempotency_key(self.idempotency_key)
        provider_code(self.provider_code)
        if not isinstance(self.status, AttemptStatus):
            raise PaymentRuleError("Invalid attempt status")
        terminal = self.status in {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED}
        if terminal != (self.completed_at is not None):
            raise PaymentRuleError("Inconsistent attempt completion")
        if self.provider_reference is not None:
            text(self.provider_reference, 255)
        if (
            self.status in {AttemptStatus.PROCESSING, AttemptStatus.SUCCEEDED}
            and self.provider_reference is None
        ):
            raise PaymentRuleError("Provider reference required")
        if self.failure_code is not None:
            code(self.failure_code)
        if self.failure_code is not None and self.status != AttemptStatus.FAILED:
            raise PaymentRuleError("Failure code only belongs to a failed attempt")
        if self.client_action is not None and self.status != AttemptStatus.PROCESSING:
            raise PaymentRuleError("Client action only belongs to processing attempts")
        if self.client_action is not None and not isinstance(
            self.client_action, ClientAction
        ):
            raise PaymentRuleError("Invalid client action")
        for timestamp in (self.created_at, self.updated_at, self.completed_at):
            if timestamp is not None:
                aware(timestamp)


@dataclass(frozen=True, kw_only=True, slots=True)
class PaymentStatusHistory:
    payment_id: UUID
    from_status: PaymentStatus | None
    to_status: PaymentStatus
    source: HistorySource
    payment_attempt_id: UUID | None = None
    changed_by_user_id: UUID | None = None
    reason: str | None = None
    provider_event_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.to_status, PaymentStatus)
            or (
                self.from_status is not None
                and not isinstance(self.from_status, PaymentStatus)
            )
            or self.from_status == self.to_status
            or (
                self.from_status is None
                and (
                    self.to_status != PaymentStatus.PENDING
                    or self.source not in {HistorySource.SYSTEM, HistorySource.CUSTOMER}
                )
            )
            or not isinstance(self.source, HistorySource)
            or (self.source == HistorySource.STAFF and self.changed_by_user_id is None)
            or (
                self.source in {HistorySource.PROVIDER, HistorySource.SYSTEM}
                and self.changed_by_user_id is not None
            )
        ):
            raise PaymentRuleError("Invalid financial history")
        if self.reason is not None:
            text(self.reason, 200)
        if self.provider_event_id is not None:
            text(self.provider_event_id, 200)
        aware(self.created_at)


@dataclass(frozen=True, kw_only=True, slots=True)
class ProviderEvent:
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
    payment_attempt_id: UUID | None = None
    reason_code: str | None = None
    processed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    received_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        provider_code(self.provider_code)
        text(self.provider_event_id, 200)
        text(self.provider_reference, 255)
        money(self.reported_amount)
        if (
            not re.fullmatch(r"[a-f0-9]{64}", self.payload_hash)
            or not re.fullmatch(r"[A-Z]{3}", self.reported_currency)
            or not isinstance(self.result, VerifiedResult)
            or not isinstance(self.processing_status, EventStatus)
            or (self.processing_status == EventStatus.RECEIVED)
            != (self.processed_at is None)
        ):
            raise PaymentRuleError("Invalid provider event evidence")
        if self.event_type is not None:
            text(self.event_type, 80)
        if self.reason_code is not None:
            code(self.reason_code)
        for timestamp in (
            self.received_at,
            self.provider_occurred_at,
            self.processed_at,
        ):
            if timestamp is not None:
                aware(timestamp)
