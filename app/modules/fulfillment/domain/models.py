import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from app.modules.orders.domain.models import OrderStatus
from app.shared.domain.time import utc_now

DELIVERY_DELAY_THRESHOLD = timedelta(minutes=15)
MAX_SECONDS = 2147483647
DELIVERY_OPERATIONAL_STATUSES = (
    OrderStatus.WAITING,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.OUT_FOR_DELIVERY,
)


class FulfillmentRuleError(ValueError):
    pass


def aware(value: datetime) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise FulfillmentRuleError("Timezone-aware timestamp required")


def clean_text(value: str, maximum: int = 2000) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(unicodedata.category(c).startswith("C") for c in value)
    ):
        raise FulfillmentRuleError("Invalid fulfillment text")
    return value.strip()


class DecisionStatus(StrEnum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, kw_only=True, slots=True)
class DeliveryAssignment:
    order_id: UUID
    assigned_user_id: UUID
    assigned_by_user_id: UUID
    assigned_at: datetime
    unassigned_at: datetime | None = None
    unassigned_by_user_id: UUID | None = None
    completed_at: datetime | None = None
    reason: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    @property
    def active(self) -> bool:
        return self.unassigned_at is None and self.completed_at is None

    def __post_init__(self) -> None:
        for value in (
            self.assigned_at,
            self.unassigned_at,
            self.completed_at,
            self.created_at,
        ):
            if value is not None:
                aware(value)
        if (
            (self.unassigned_at is None) != (self.unassigned_by_user_id is None)
            or (self.unassigned_at is not None and self.completed_at is not None)
            or (
                self.unassigned_at is not None and self.unassigned_at < self.assigned_at
            )
            or (self.completed_at is not None and self.completed_at < self.assigned_at)
        ):
            raise FulfillmentRuleError("Inconsistent assignment history")
        if self.reason is not None:
            clean_text(self.reason, 200)


@dataclass(frozen=True, kw_only=True, slots=True)
class DeliveryDelayIncident:
    order_id: UUID
    branch_id: UUID
    committed_eta: datetime
    observed_order_status: OrderStatus
    delay_seconds_at_detection: int
    detected_at: datetime
    delay_threshold_seconds: int = 900
    decision_status: DecisionStatus = DecisionStatus.OPEN
    evaluated_by_user_id: UUID | None = None
    evaluated_at: datetime | None = None
    customer_responsibility: bool | None = None
    evaluation_note: str | None = None
    remediation_description: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for value in (
            self.committed_eta,
            self.detected_at,
            self.evaluated_at,
            self.created_at,
            self.updated_at,
        ):
            if value is not None:
                aware(value)
        if (
            type(self.delay_seconds_at_detection) is not int
            or self.delay_threshold_seconds != 900
            or not 900 < self.delay_seconds_at_detection <= MAX_SECONDS
            or not isinstance(self.observed_order_status, OrderStatus)
            or self.observed_order_status
            not in (*DELIVERY_OPERATIONAL_STATUSES, OrderStatus.DELIVERED)
            or not isinstance(self.decision_status, DecisionStatus)
            or (
                self.customer_responsibility is not None
                and type(self.customer_responsibility) is not bool
            )
        ):
            raise FulfillmentRuleError("Invalid delivery delay evidence")
        if self.decision_status == DecisionStatus.OPEN:
            if any(
                v is not None
                for v in (
                    self.evaluated_at,
                    self.evaluated_by_user_id,
                    self.customer_responsibility,
                    self.evaluation_note,
                    self.remediation_description,
                )
            ):
                raise FulfillmentRuleError("Open incident cannot have evaluation")
        elif (
            self.evaluated_at is None
            or self.evaluated_by_user_id is None
            or self.evaluated_at < self.detected_at
        ):
            raise FulfillmentRuleError("Evaluation provenance required")
        if self.decision_status == DecisionStatus.APPROVED:
            clean_text(self.remediation_description)
        elif self.remediation_description is not None:
            raise FulfillmentRuleError("Only approval has a remediation")
        if self.evaluation_note is not None:
            clean_text(self.evaluation_note)
