from datetime import datetime

from app.modules.orders.domain.models import (
    Order,
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    aware,
)

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


def validate_transition(order: Order, target: OrderStatus) -> None:
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


def status_after_payment(order: Order, now: datetime) -> OrderStatus:
    """Future Payments policy only. No endpoint or payment write is provided."""
    aware(now)
    if (
        order.status != OrderStatus.PENDING_PAYMENT
        or order.payment_method_type != PaymentMethodType.ONLINE
    ):
        raise OrderRuleError("Order is not awaiting an online payment")
    if (
        order.pickup_details
        and now < order.pickup_details.calculated_kitchen_release_at
    ):
        return OrderStatus.SCHEDULED
    return OrderStatus.WAITING
