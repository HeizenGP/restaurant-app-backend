"""Kitchen read models and timing policies; no second Order lifecycle."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.orders.domain.models import OrderMode, OrderStatus, StatusHistory

KITCHEN_STATUSES = (
    OrderStatus.WAITING,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.READY_FOR_PICKUP,
)


class KitchenDataError(ValueError):
    """Persisted operational data is inconsistent, not invalid client input."""


def aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise KitchenDataError("Kitchen timestamps must be timezone-aware")


def target_ready_status(mode: OrderMode) -> OrderStatus:
    if not isinstance(mode, OrderMode):
        raise KitchenDataError("Unknown order mode")
    return (
        OrderStatus.READY_FOR_PICKUP if mode == OrderMode.PICKUP else OrderStatus.READY
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenAddon:
    addon_name_snapshot: str
    option_name_snapshot: str


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenItem:
    product_name_snapshot: str
    presentation_name_snapshot: str
    quantity: int
    notes: str | None
    addon_options: tuple[KitchenAddon, ...] = ()


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenOrderSnapshot:
    id: UUID
    order_number: int
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    created_at: datetime
    confirmed_at: datetime
    items: tuple[KitchenItem, ...]
    history: tuple[StatusHistory, ...]
    table_label: str | None = None
    requested_pickup_at: datetime | None = None
    estimated_ready_at: datetime | None = None
    estimated_delivery_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            self.status not in KITCHEN_STATUSES
            or not isinstance(self.mode, OrderMode)
            or not self.items
            or self.confirmed_at is None
            or self.order_number < 1
            or (self.status == OrderStatus.READY and self.mode == OrderMode.PICKUP)
            or (
                self.status == OrderStatus.READY_FOR_PICKUP
                and self.mode != OrderMode.PICKUP
            )
            or (self.mode == OrderMode.LOCAL and not self.table_label)
            or (
                self.mode == OrderMode.PICKUP
                and (
                    self.requested_pickup_at is None or self.estimated_ready_at is None
                )
            )
            or (self.mode == OrderMode.DELIVERY and self.estimated_delivery_at is None)
        ):
            raise KitchenDataError("Incomplete operational order")
        for timestamp in (
            self.created_at,
            self.confirmed_at,
            self.requested_pickup_at,
            self.estimated_ready_at,
            self.estimated_delivery_at,
        ):
            if timestamp is not None:
                aware(timestamp)


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenTiming:
    entered_waiting_at: datetime
    started_preparing_at: datetime | None
    ready_at: datetime | None
    waiting_seconds: int
    preparation_seconds: int
    current_status_seconds: int


def timing_for(order: KitchenOrderSnapshot, now: datetime) -> KitchenTiming:
    aware(now)
    entries = {}
    history = order.history
    for entry in history:
        aware(entry.created_at)
        if entry.to_status in KITCHEN_STATUSES:
            if entry.to_status in entries:
                raise KitchenDataError("Duplicate preparation history")
            entries[entry.to_status] = entry.created_at
    waiting = entries.get(OrderStatus.WAITING)
    preparing = entries.get(OrderStatus.PREPARING)
    ready = entries.get(target_ready_status(order.mode))
    if (
        not history
        or entries.get(order.status) != max(entry.created_at for entry in history)
        or waiting is None
        or (order.status == OrderStatus.WAITING and (preparing or ready))
        or (order.status == OrderStatus.PREPARING and ready is not None)
        or (order.status != OrderStatus.WAITING and preparing is None)
        or (
            order.status in {OrderStatus.READY, OrderStatus.READY_FOR_PICKUP}
            and ready is None
        )
        or (preparing is not None and preparing < waiting)
        or (ready is not None and (preparing is None or ready < preparing))
    ):
        raise KitchenDataError("Missing or inconsistent preparation history")

    def seconds(end: datetime, start: datetime) -> int:
        return max(0, int((end - start).total_seconds()))

    return KitchenTiming(
        entered_waiting_at=waiting,
        started_preparing_at=preparing,
        ready_at=ready,
        waiting_seconds=seconds(preparing or now, waiting),
        preparation_seconds=seconds(ready or now, preparing) if preparing else 0,
        current_status_seconds=seconds(now, entries[order.status]),
    )
