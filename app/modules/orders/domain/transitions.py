from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.modules.orders.domain.models import (
    Order,
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    aware,
)

if TYPE_CHECKING:
    from app.modules.orders.domain.lifecycle import OrderTransitionContext
    from app.modules.orders.domain.payments import OrderPaymentContext

QUEUE_STATUSES = (OrderStatus.WAITING, OrderStatus.PREPARING)


def flow(mode: OrderMode, method: PaymentMethodType) -> tuple[OrderStatus, ...]:
    if mode == OrderMode.PICKUP:
        return (
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.SCHEDULED,
            OrderStatus.WAITING,
            OrderStatus.PREPARING,
            OrderStatus.READY_FOR_PICKUP,
            OrderStatus.PICKED_UP,
        )
    if mode == OrderMode.DELIVERY:
        return (
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.WAITING,
            OrderStatus.PREPARING,
            OrderStatus.READY,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.DELIVERED,
        )
    return (
        OrderStatus.PENDING_PAYMENT
        if method == PaymentMethodType.ONLINE
        else OrderStatus.PENDING_CASH_CONFIRMATION,
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.SERVED,
    )


def allowed_statuses(mode: OrderMode, method: PaymentMethodType) -> set[OrderStatus]:
    return {*flow(mode, method), OrderStatus.CANCELLED}


def validate_transition(
    order: Order | OrderTransitionContext | OrderPaymentContext, target: OrderStatus
) -> None:
    route = flow(order.mode, order.payment_method_type)
    if order.status not in route or order.status == route[-1]:
        raise OrderRuleError("Terminal order cannot transition")
    index = route.index(order.status)
    allowed = {route[index + 1]}
    if order.mode == OrderMode.PICKUP and order.status == OrderStatus.PENDING_PAYMENT:
        allowed.add(OrderStatus.WAITING)
    if target not in allowed:
        raise OrderRuleError("Impossible order transition")
    if (
        order.payment_method_type == PaymentMethodType.ONLINE
        and order.payment_status != PaymentStatus.PAID
    ):
        raise OrderRuleError("Online payment must be confirmed first")


def status_after_payment(
    order: Order | OrderPaymentContext, now: datetime
) -> OrderStatus:
    """Orders owns the online activation decision, including pickup release."""
    aware(now)
    if (
        order.status != OrderStatus.PENDING_PAYMENT
        or order.payment_method_type != PaymentMethodType.ONLINE
    ):
        raise OrderRuleError("Order is not awaiting an online payment")
    release_at = (
        order.pickup_details.calculated_kitchen_release_at
        if isinstance(order, Order) and order.pickup_details
        else None
        if isinstance(order, Order)
        else order.calculated_kitchen_release_at
    )
    if order.mode == OrderMode.PICKUP and release_at is not None and now < release_at:
        return OrderStatus.SCHEDULED
    return OrderStatus.WAITING
