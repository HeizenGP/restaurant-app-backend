"""Orders-owned payment context and activation policy; no Payments ORM."""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    aware,
    money,
)
from app.modules.orders.domain.transitions import (
    status_after_payment,
    validate_transition,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class OrderPaymentContext:
    id: UUID
    customer_id: UUID
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    payment_method_type: PaymentMethodType
    payment_status: PaymentStatus
    total: Decimal
    confirmed_at: datetime | None
    calculated_kitchen_release_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                isinstance(self.mode, OrderMode),
                isinstance(self.status, OrderStatus),
                isinstance(self.payment_method_type, PaymentMethodType),
                isinstance(self.payment_status, PaymentStatus),
            )
        ):
            raise OrderRuleError("Invalid payment context")
        money(self.total)
        if self.confirmed_at is not None:
            aware(self.confirmed_at)
        if self.calculated_kitchen_release_at is not None:
            aware(self.calculated_kitchen_release_at)
        if self.mode == OrderMode.PICKUP and self.calculated_kitchen_release_at is None:
            raise OrderRuleError(
                "Pickup payment context requires its release timestamp"
            )


def payment_confirmation_target(
    order: OrderPaymentContext, now: datetime, *, online: bool
) -> OrderStatus:
    aware(now)
    expected = PaymentMethodType.ONLINE if online else PaymentMethodType.CASH
    if order.payment_method_type != expected:
        raise OrderRuleError("Payment method does not match order")
    if not online:
        if order.mode != OrderMode.LOCAL or order.status == OrderStatus.CANCELLED:
            raise OrderRuleError("Cash confirmation is not allowed")
        return order.status
    if order.status == OrderStatus.CANCELLED:
        # Preserve financial truth, never resurrect a cancelled order.
        return order.status
    if order.payment_status == PaymentStatus.PAID:
        return order.status
    target = status_after_payment(order, now)
    validate_transition(replace(order, payment_status=PaymentStatus.PAID), target)
    return target
