import re
from dataclasses import replace
from datetime import datetime, timedelta
from math import ceil
from uuid import UUID

from app.modules.fulfillment.domain.models import (
    DELIVERY_DELAY_THRESHOLD,
    DELIVERY_OPERATIONAL_STATUSES,
    MAX_SECONDS,
    DecisionStatus,
    DeliveryDelayIncident,
    FulfillmentRuleError,
    aware,
    clean_text,
)
from app.modules.orders.domain.fulfillment import OrderFulfillmentContext
from app.modules.orders.domain.models import BranchOrderSettings, OrderMode, OrderStatus


def recommended_release(
    requested: datetime, settings: BranchOrderSettings, queue_depth: int
) -> tuple[datetime, datetime]:
    aware(requested)
    if type(queue_depth) is not int or queue_depth < 0:
        raise FulfillmentRuleError("Invalid queue depth")
    try:
        ready = requested - timedelta(minutes=settings.pickup_buffer_minutes)
        release = ready - timedelta(
            minutes=settings.default_prep_minutes
            + queue_depth * settings.queue_delay_per_order_minutes
        )
    except OverflowError:
        raise FulfillmentRuleError("Unrepresentable pickup schedule") from None
    return release, ready


def normalized_name(value: str) -> str:
    return " ".join(clean_text(value, 180).split()).casefold()


def normalized_phone(value: str) -> str:
    # Existing identity uses optional + and 9..15 ASCII digits; no country guesses.
    value = clean_text(value, 40)
    if not re.fullmatch(r"[+0-9 ()-]+", value, flags=re.ASCII):
        raise FulfillmentRuleError("Invalid full phone number")
    value = re.sub(r"[ ()-]", "", value)
    if not re.fullmatch(r"[+]?[0-9]{9,15}", value, flags=re.ASCII):
        raise FulfillmentRuleError("Invalid full phone number")
    return value.removeprefix("+")


def identity_matches(
    name: str, phone: str, snapshot_name: str, snapshot_phone: str
) -> bool:
    return normalized_name(name) == normalized_name(snapshot_name) and normalized_phone(
        phone
    ) == normalized_phone(snapshot_phone)


def delay_seconds(order: OrderFulfillmentContext, now: datetime) -> int:
    aware(now)
    if order.mode != OrderMode.DELIVERY or order.status == OrderStatus.CANCELLED:
        return 0
    reference = order.delivered_at if order.status == OrderStatus.DELIVERED else now
    if reference is None or order.estimated_delivery_at is None:
        raise FulfillmentRuleError("Missing delivery timing evidence")
    return min(
        MAX_SECONDS,
        max(0, ceil((reference - order.estimated_delivery_at).total_seconds())),
    )


def is_delayed(order: OrderFulfillmentContext, now: datetime) -> bool:
    aware(now)
    if order.mode != OrderMode.DELIVERY or order.status not in (
        *DELIVERY_OPERATIONAL_STATUSES,
        OrderStatus.DELIVERED,
    ):
        return False
    reference = order.delivered_at if order.status == OrderStatus.DELIVERED else now
    return (
        reference is not None
        and reference > order.estimated_delivery_at + DELIVERY_DELAY_THRESHOLD
    )


def evaluate_incident(
    incident: DeliveryDelayIncident,
    target: DecisionStatus,
    actor: UUID,
    now: datetime,
    responsibility: bool | None,
    note: str | None,
    remediation: str | None,
) -> DeliveryDelayIncident:
    if target not in {
        DecisionStatus.APPROVED,
        DecisionStatus.REJECTED,
    } or not isinstance(target, DecisionStatus):
        raise FulfillmentRuleError("Invalid delay decision")
    note = clean_text(note) if note is not None else None
    remediation = clean_text(remediation) if remediation is not None else None
    if target == DecisionStatus.APPROVED and remediation is None:
        raise FulfillmentRuleError("Remediation description required")
    if target == DecisionStatus.REJECTED and remediation is not None:
        raise FulfillmentRuleError("Rejection has no remediation")
    if incident.decision_status != DecisionStatus.OPEN:
        if (
            incident.decision_status,
            incident.evaluated_by_user_id,
            incident.customer_responsibility,
            incident.evaluation_note,
            incident.remediation_description,
        ) == (target, actor, responsibility, note, remediation):
            return incident
        raise FulfillmentRuleError("Incident already decided")
    return replace(
        incident,
        decision_status=target,
        evaluated_by_user_id=actor,
        evaluated_at=now,
        customer_responsibility=responsibility,
        evaluation_note=note,
        remediation_description=remediation,
        updated_at=now,
    )
