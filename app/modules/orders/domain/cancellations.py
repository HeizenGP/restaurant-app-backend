"""Public cancellation policy; deliberately separate from sequential advancement."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    money,
)

CANCELLABLE_STATUSES = frozenset(
    {
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PENDING_CASH_CONFIRMATION,
        OrderStatus.SCHEDULED,
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.READY_FOR_PICKUP,
        OrderStatus.OUT_FOR_DELIVERY,
    }
)


@dataclass(frozen=True, kw_only=True, slots=True)
class OrderCancellationContext:
    id: UUID
    customer_id: UUID
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    payment_method_type: PaymentMethodType
    payment_status: PaymentStatus
    total: Decimal

    def __post_init__(self):
        if not (
            isinstance(self.mode, OrderMode)
            and isinstance(self.status, OrderStatus)
            and isinstance(self.payment_method_type, PaymentMethodType)
            and isinstance(self.payment_status, PaymentStatus)
        ):
            raise OrderRuleError("Invalid cancellation context")
        money(self.total)


def validate_cancellation(order: OrderCancellationContext) -> None:
    if order.status not in CANCELLABLE_STATUSES:
        raise OrderRuleError("Order is not cancellable")
