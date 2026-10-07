from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.orders.domain.models import (
    BranchOrderSettings,
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    aware,
)


def initial_status(
    mode: OrderMode, method: PaymentMethodType, settings: BranchOrderSettings
) -> OrderStatus:
    if mode != OrderMode.LOCAL and method != PaymentMethodType.ONLINE:
        raise OrderRuleError("Online prepayment is required")
    if method == PaymentMethodType.ONLINE:
        return OrderStatus.PENDING_PAYMENT
    return (
        OrderStatus.PENDING_CASH_CONFIRMATION
        if settings.cash_payment_requires_confirmation
        else OrderStatus.WAITING
    )


def pickup_times(
    now: datetime, requested: datetime, prep_minutes: int, buffer_minutes: int
) -> tuple[datetime, datetime]:
    aware(now)
    aware(requested)
    requested = requested.astimezone(UTC)
    ready = requested - timedelta(minutes=buffer_minutes)
    release = ready - timedelta(minutes=prep_minutes)
    if requested <= now or release < now:
        raise OrderRuleError("Pickup time cannot be met")
    return release, ready


def within_branch_hours(
    requested: datetime,
    timezone: str,
    hours: tuple[tuple[int, time | None, time | None, bool], ...],
) -> bool:
    """0=Monday. No configured hours means no invented closing time."""
    aware(requested)
    if not hours:
        return True
    local = requested.astimezone(ZoneInfo(timezone))
    current_time = local.time().replace(tzinfo=None)
    for day, opens, closes, closed in hours:
        if closed or opens is None or closes is None:
            continue
        if opens < closes and day == local.weekday() and opens <= current_time < closes:
            return True
        if opens > closes and (
            (day == local.weekday() and current_time >= opens)
            or ((day + 1) % 7 == local.weekday() and current_time < closes)
        ):
            return True
    return False
