from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.fulfillment.domain.models import DeliveryAssignment
from app.modules.orders.domain.fulfillment import OrderFulfillmentContext
from app.modules.orders.domain.models import OrderStatus


@dataclass(frozen=True, kw_only=True)
class PickupRecommendation:
    order_id: UUID
    order_number: int
    requested_pickup_at: datetime
    initial_release_at: datetime
    recommended_release_at: datetime
    estimated_ready_at: datetime
    initial_estimated_ready_at: datetime
    queue_depth: int
    minutes_until_release: int
    is_due: bool


@dataclass(frozen=True, kw_only=True)
class TransitionResult:
    order_id: UUID
    order_number: int
    status: OrderStatus
    changed: bool


@dataclass(frozen=True, kw_only=True)
class BulkReleaseResult:
    evaluated: int
    released: int
    orders: tuple[TransitionResult, ...]
    queue_depth: int


@dataclass(frozen=True, kw_only=True)
class DelayDetectionResult:
    evaluated: int
    new_incidents: int
    existing_incidents: int
    next_order_number: int | None


@dataclass(frozen=True, kw_only=True)
class DeliveryQueueCard:
    order: OrderFulfillmentContext
    active_assignment: DeliveryAssignment | None
    current_delay_seconds: int
    is_delayed: bool
