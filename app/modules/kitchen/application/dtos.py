from dataclasses import dataclass, fields
from datetime import datetime

from app.modules.kitchen.domain.models import (
    KITCHEN_STATUSES,
    KitchenDataError,
    KitchenOrderSnapshot,
    KitchenTiming,
    timing_for,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenQueueQuery:
    limit: int = 100
    offset: int = 0
    mode: OrderMode | None = None
    status: OrderStatus | None = None

    def __post_init__(self) -> None:
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= 200
            or type(self.offset) is not int
            or not 0 <= self.offset <= 100_000
            or (self.mode is not None and not isinstance(self.mode, OrderMode))
            or (self.status is not None and self.status not in KITCHEN_STATUSES)
        ):
            raise ValueError("Invalid kitchen queue query")


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenOrder(KitchenOrderSnapshot):
    generated_at: datetime
    timing: KitchenTiming


def kitchen_order(snapshot: KitchenOrderSnapshot, now: datetime) -> KitchenOrder:
    return KitchenOrder(
        **{field.name: getattr(snapshot, field.name) for field in fields(snapshot)},
        generated_at=now,
        timing=timing_for(snapshot, now),
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class KitchenQueue:
    generated_at: datetime
    waiting: tuple[KitchenOrder, ...]
    preparing: tuple[KitchenOrder, ...]
    ready: tuple[KitchenOrder, ...]
    limit: int
    offset: int
    has_more: bool


def group_queue(
    orders: list[KitchenOrderSnapshot], now: datetime, query: KitchenQueueQuery
) -> KitchenQueue:
    groups = {name: [] for name in ("waiting", "preparing", "ready")}
    for order in orders[: query.limit]:
        card = kitchen_order(order, now)
        name = (
            "waiting"
            if card.status == OrderStatus.WAITING
            else "preparing"
            if card.status == OrderStatus.PREPARING
            else "ready"
        )
        groups[name].append(card)

    def key(card: KitchenOrder):
        timestamp = (
            card.timing.entered_waiting_at
            if card.status == OrderStatus.WAITING
            else card.timing.started_preparing_at
            if card.status == OrderStatus.PREPARING
            else card.timing.ready_at
        )
        if timestamp is None:
            raise KitchenDataError("Missing queue timestamp")
        return timestamp, card.order_number, card.id

    return KitchenQueue(
        generated_at=now,
        **{name: tuple(sorted(cards, key=key)) for name, cards in groups.items()},
        limit=query.limit,
        offset=query.offset,
        has_more=len(orders) > query.limit,
    )
