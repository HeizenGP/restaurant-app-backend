"""Stable, minimal Orders contract for internal preparation operations."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
    aware,
)
from app.modules.orders.domain.transitions import validate_transition


@dataclass(frozen=True, kw_only=True, slots=True)
class OrderTransitionContext:
    id: UUID
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    payment_method_type: PaymentMethodType
    payment_status: PaymentStatus
    confirmed_at: datetime | None

    def __post_init__(self) -> None:
        if not (
            isinstance(self.mode, OrderMode)
            and isinstance(self.status, OrderStatus)
            and isinstance(self.payment_method_type, PaymentMethodType)
            and isinstance(self.payment_status, PaymentStatus)
        ):
            raise OrderRuleError("Invalid order transition context")
        if self.confirmed_at is not None:
            aware(self.confirmed_at)


def validate_preparation_transition(
    order: OrderTransitionContext, history: StatusHistory
) -> None:
    """Not a public arbitrary-status setter; Orders still owns its graph."""
    aware(history.created_at)
    if (
        not isinstance(history.to_status, OrderStatus)
        or history.from_status != order.status
        or history.to_status
        not in {OrderStatus.PREPARING, OrderStatus.READY, OrderStatus.READY_FOR_PICKUP}
        or history.changed_by_user_id is None
        or order.confirmed_at is None
    ):
        raise OrderRuleError("Invalid preparation transition")
    validate_transition(order, history.to_status)
