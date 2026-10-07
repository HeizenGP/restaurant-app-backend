from dataclasses import dataclass

from app.modules.notifications.domain.models import (
    NotificationKind,
    NotificationRuleError,
    cursor,
)


@dataclass(frozen=True, slots=True)
class NotificationContent:
    title: str
    body: str


def content(kind: NotificationKind, order_number: int) -> NotificationContent:
    if not isinstance(kind, NotificationKind) or cursor(order_number) == 0:
        raise NotificationRuleError("Invalid notification content source")
    titles = {
        NotificationKind.ORDER_RECEIVED: "Pedido recibido",
        NotificationKind.ORDER_PREPARING: "Pedido en preparación",
        NotificationKind.ORDER_READY: "Pedido listo",
        NotificationKind.ORDER_READY_FOR_PICKUP: "Pedido listo para recojo",
        NotificationKind.ORDER_OUT_FOR_DELIVERY: "Pedido en camino",
        NotificationKind.ORDER_DELIVERED: "Pedido entregado",
        NotificationKind.DELIVERY_DELAYED: "Tu delivery presenta un retraso",
    }
    bodies = {
        NotificationKind.ORDER_RECEIVED: "Recibimos tu pedido #{number}.",
        NotificationKind.ORDER_PREPARING: (
            "Tu pedido #{number} ya está siendo preparado."
        ),
        NotificationKind.ORDER_READY: "Tu pedido #{number} está listo.",
        NotificationKind.ORDER_READY_FOR_PICKUP: (
            "Tu pedido #{number} ya está listo para recoger."
        ),
        NotificationKind.ORDER_OUT_FOR_DELIVERY: (
            "Tu pedido #{number} salió a delivery."
        ),
        NotificationKind.ORDER_DELIVERED: "Tu pedido #{number} fue entregado.",
        NotificationKind.DELIVERY_DELAYED: (
            "Tu pedido #{number} está demorando más de lo estimado."
        ),
    }
    return NotificationContent(titles[kind], bodies[kind].format(number=order_number))
