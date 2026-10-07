"""Minimal public Orders contract for fulfillment; no second lifecycle."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.orders.domain.lifecycle import OrderTransitionContext
from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
    aware,
    text_value,
)
from app.modules.orders.domain.transitions import validate_transition


@dataclass(frozen=True, kw_only=True)
class OrderFulfillmentContext(OrderTransitionContext):
    order_number: int
    requested_pickup_at: datetime | None = None
    calculated_kitchen_release_at: datetime | None = None
    estimated_ready_at: datetime | None = None
    pickup_name_snapshot: str | None = None
    pickup_phone_snapshot: str | None = None
    estimated_delivery_at: datetime | None = None
    delivery_zone_name_snapshot: str | None = None
    recipient_name_snapshot: str | None = None
    recipient_phone_snapshot: str | None = None
    address_line_snapshot: str | None = None
    reference_text_snapshot: str | None = None
    district_snapshot: str | None = None
    city_snapshot: str | None = None
    department_snapshot: str | None = None
    waiting_at: datetime | None = None
    preparing_at: datetime | None = None
    ready_at: datetime | None = None
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    delivered_history_count: int = 0

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.order_number) is not int or self.order_number < 1:
            raise OrderRuleError("Invalid order number")
        for name in (
            "requested_pickup_at",
            "calculated_kitchen_release_at",
            "estimated_ready_at",
            "estimated_delivery_at",
            "waiting_at",
            "preparing_at",
            "ready_at",
            "dispatched_at",
            "delivered_at",
        ):
            if (value := getattr(self, name)) is not None:
                aware(value)
        if self.mode == OrderMode.PICKUP:
            if any(
                getattr(self, n) is None
                for n in (
                    "requested_pickup_at",
                    "calculated_kitchen_release_at",
                    "estimated_ready_at",
                    "pickup_name_snapshot",
                    "pickup_phone_snapshot",
                )
            ):
                raise OrderRuleError("Missing pickup snapshot")
            if (
                not self.calculated_kitchen_release_at
                <= self.estimated_ready_at
                <= self.requested_pickup_at
            ):
                raise OrderRuleError("Inconsistent pickup snapshot")
            text_value(self.pickup_name_snapshot)
            text_value(self.pickup_phone_snapshot, 20)
        if self.mode == OrderMode.DELIVERY:
            for name in (
                "delivery_zone_name_snapshot",
                "recipient_name_snapshot",
                "recipient_phone_snapshot",
                "address_line_snapshot",
                "district_snapshot",
                "city_snapshot",
                "department_snapshot",
            ):
                text_value(getattr(self, name), 500)
            if self.estimated_delivery_at is None:
                raise OrderRuleError("Missing committed delivery ETA")
            if self.status == OrderStatus.DELIVERED and (
                self.delivered_history_count != 1 or self.delivered_at is None
            ):
                raise OrderRuleError("Missing or ambiguous delivered history")


def validate_fulfillment_transition(
    order: OrderFulfillmentContext, history: StatusHistory
) -> None:
    """Explicit allowed actions; still validated by the single Orders graph."""
    sources = {
        (OrderMode.PICKUP, OrderStatus.SCHEDULED): OrderStatus.WAITING,
        (OrderMode.PICKUP, OrderStatus.READY_FOR_PICKUP): OrderStatus.PICKED_UP,
        (OrderMode.DELIVERY, OrderStatus.READY): OrderStatus.OUT_FOR_DELIVERY,
        (OrderMode.DELIVERY, OrderStatus.OUT_FOR_DELIVERY): OrderStatus.DELIVERED,
    }
    if (
        sources.get((order.mode, order.status)) != history.to_status
        or history.from_status != order.status
        or history.changed_by_user_id is None
        or order.payment_method_type != PaymentMethodType.ONLINE
        or order.payment_status != PaymentStatus.PAID
        or order.confirmed_at is None
    ):
        raise OrderRuleError("Invalid fulfillment transition")
    aware(history.created_at)
    validate_transition(order, history.to_status)
