from dataclasses import replace
from datetime import datetime

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.domain.models import (
    AttemptStatus,
    ClientAction,
    Payment,
    PaymentAttempt,
    PaymentRuleError,
    PaymentStatus,
    aware,
)


def transition_payment(
    payment: Payment, target: PaymentStatus, now: datetime
) -> Payment:
    aware(now)
    routes = {
        PaymentStatus.PENDING: {PaymentStatus.PROCESSING},
        PaymentStatus.PROCESSING: {PaymentStatus.PAID, PaymentStatus.FAILED},
        PaymentStatus.FAILED: {PaymentStatus.PROCESSING},
        PaymentStatus.PAID: set(),
    }
    if payment.method_type == PaymentMethodType.CASH:
        routes = {
            PaymentStatus.PENDING: {PaymentStatus.PAID},
            PaymentStatus.PAID: set(),
        }
    if not isinstance(target, PaymentStatus) or target not in routes[payment.status]:
        raise PaymentRuleError("Invalid payment transition")
    return replace(
        payment,
        status=target,
        updated_at=now,
        paid_at=now if target == PaymentStatus.PAID else None,
    )


def transition_attempt(
    attempt: PaymentAttempt,
    target: AttemptStatus,
    now: datetime,
    *,
    verified_capture: bool = False,
    provider_reference: str | None = None,
    client_action: ClientAction | None = None,
    failure_code: str | None = None,
) -> PaymentAttempt:
    aware(now)
    routes = {
        AttemptStatus.CREATED: {AttemptStatus.PROCESSING, AttemptStatus.FAILED},
        AttemptStatus.PROCESSING: {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED},
        AttemptStatus.FAILED: set(),
        AttemptStatus.SUCCEEDED: set(),
    }
    if verified_capture:
        routes[AttemptStatus.CREATED].add(AttemptStatus.SUCCEEDED)
        routes[AttemptStatus.FAILED].add(AttemptStatus.SUCCEEDED)
    if not isinstance(target, AttemptStatus) or target not in routes[attempt.status]:
        raise PaymentRuleError("Invalid attempt transition")
    return replace(
        attempt,
        status=target,
        updated_at=now,
        completed_at=now
        if target in {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED}
        else None,
        provider_reference=provider_reference or attempt.provider_reference,
        client_action=client_action,
        failure_code=failure_code,
    )
