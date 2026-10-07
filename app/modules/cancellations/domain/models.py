import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.shared.domain.time import utc_now


class CancellationRuleError(ValueError):
    pass


def plain_text(value: str, maximum: int = 1000) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "<" in value
        or ">" in value
        or any(unicodedata.category(c).startswith("C") for c in value)
    ):
        raise CancellationRuleError("Invalid plain cancellation text")
    return value.strip()


def aware(value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CancellationRuleError("Timezone-aware timestamp required")


class RequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CancellationSource(StrEnum):
    ADMIN = "ADMIN"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class ReasonCode(StrEnum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    OTHER = "OTHER"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


@dataclass(frozen=True, kw_only=True, slots=True)
class CancellationRequest:
    order_id: UUID
    customer_id: UUID
    branch_id: UUID
    reason: str
    requested_at: datetime
    status: RequestStatus = RequestStatus.PENDING
    evaluated_by_user_id: UUID | None = None
    evaluated_at: datetime | None = None
    evaluation_note: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        if plain_text(self.reason) != self.reason or not isinstance(
            self.status, RequestStatus
        ):
            raise CancellationRuleError("Invalid request")
        for value in (
            self.requested_at,
            self.evaluated_at,
            self.created_at,
            self.updated_at,
        ):
            if value is not None:
                aware(value)
        if self.status == RequestStatus.PENDING:
            if any(
                v is not None
                for v in (
                    self.evaluated_by_user_id,
                    self.evaluated_at,
                    self.evaluation_note,
                )
            ):
                raise CancellationRuleError("Pending request cannot have evaluation")
        elif (
            self.evaluated_by_user_id is None
            or self.evaluated_at is None
            or self.evaluated_at < self.requested_at
        ):
            raise CancellationRuleError("Evaluation provenance required")
        if self.evaluation_note is not None:
            if plain_text(self.evaluation_note, 2000) != self.evaluation_note:
                raise CancellationRuleError("Evaluation must be normalized")


@dataclass(frozen=True, kw_only=True, slots=True)
class OrderCancellation:
    order_id: UUID
    branch_id: UUID
    source: CancellationSource
    reason_code: ReasonCode
    cancelled_by_user_id: UUID
    cancelled_at: datetime
    cancellation_request_id: UUID | None = None
    reason_text: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self):
        aware(self.cancelled_at)
        aware(self.created_at)
        if not isinstance(self.source, CancellationSource) or not isinstance(
            self.reason_code, ReasonCode
        ):
            raise CancellationRuleError("Invalid cancellation source")
        if self.source == CancellationSource.CUSTOMER_REQUEST:
            if (
                self.cancellation_request_id is None
                or self.reason_code != ReasonCode.CUSTOMER_REQUEST
            ):
                raise CancellationRuleError("Request provenance required")
        elif (
            self.reason_code == ReasonCode.CUSTOMER_REQUEST
            or self.cancellation_request_id is not None
        ):
            raise CancellationRuleError(
                "Direct cancellation cannot impersonate a request"
            )
        if self.reason_code == ReasonCode.OTHER and self.reason_text is None:
            raise CancellationRuleError("Administrative reason required")
        if (
            self.reason_text is not None
            and plain_text(self.reason_text) != self.reason_text
        ):
            raise CancellationRuleError("Reason must be normalized")
