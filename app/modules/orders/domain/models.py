from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.cart.domain.models import (
    ZERO,
    CartRuleError,
    normalize_notes,
    snapshot_money,
    validate_quantity,
)
from app.shared.domain.time import utc_now


class OrderRuleError(ValueError):
    """Pure historical order invariant violation."""


class OrderMode(StrEnum):
    LOCAL = "LOCAL"
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PENDING_CASH_CONFIRMATION = "PENDING_CASH_CONFIRMATION"
    SCHEDULED = "SCHEDULED"
    WAITING = "WAITING"
    PREPARING = "PREPARING"
    READY = "READY"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    SERVED = "SERVED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PaymentMethodType(StrEnum):
    ONLINE = "ONLINE"
    CASH = "CASH"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"


def money(value: Decimal) -> Decimal:
    try:
        return snapshot_money(value)
    except CartRuleError:
        raise OrderRuleError("Invalid monetary value") from None


def text_value(value: str, maximum: int = 180) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise OrderRuleError("Invalid text")
    return value


def aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OrderRuleError("Timezone is required")


@dataclass(frozen=True, kw_only=True)
class BranchOrderSettings:
    branch_id: UUID
    cash_payment_requires_confirmation: bool = True
    delivery_minimum_order: Decimal = ZERO
    default_prep_minutes: int = 20
    queue_delay_per_order_minutes: int = 5
    pickup_buffer_minutes: int = 5
    delivery_default_travel_minutes: int = 20
    timezone: str = "America/Lima"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        money(self.delivery_minimum_order)
        if type(self.cash_payment_requires_confirmation) is not bool:
            raise OrderRuleError("Invalid confirmation policy")
        for name in (
            "default_prep_minutes",
            "queue_delay_per_order_minutes",
            "pickup_buffer_minutes",
            "delivery_default_travel_minutes",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 1440:
                raise OrderRuleError("Minutes must be between 0 and 1440")
        if self.default_prep_minutes < 1:
            raise OrderRuleError("Preparation must take at least one minute")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise OrderRuleError("Unknown timezone") from None


@dataclass(frozen=True, kw_only=True)
class RestaurantTable:
    branch_id: UUID
    label: str
    id: UUID = field(default_factory=uuid4)
    qr_token: UUID = field(default_factory=uuid4)
    is_active: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        text_value(self.label, 80)


@dataclass(frozen=True, kw_only=True)
class DeliveryZone:
    branch_id: UUID | None
    name: str
    district: str
    delivery_fee: Decimal
    is_free: bool = False
    estimated_travel_minutes: int | None = None
    is_active: bool = True
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        text_value(self.name, 120)
        text_value(self.district, 120)
        money(self.delivery_fee)
        if self.is_free and self.delivery_fee != ZERO:
            raise OrderRuleError("Free zone cannot charge a fee")
        if self.estimated_travel_minutes is not None and (
            type(self.estimated_travel_minutes) is not int
            or not 0 <= self.estimated_travel_minutes <= 1440
        ):
            raise OrderRuleError("Invalid travel minutes")


@dataclass(frozen=True, kw_only=True)
class OrderAddonOption:
    product_addon_id: UUID
    product_addon_option_id: UUID
    addon_name_snapshot: str
    option_name_snapshot: str
    additional_price_snapshot: Decimal
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        text_value(self.addon_name_snapshot)
        text_value(self.option_name_snapshot)
        money(self.additional_price_snapshot)


@dataclass(frozen=True, kw_only=True)
class OrderItem:
    product_id: UUID
    presentation_id: UUID
    product_name_snapshot: str
    presentation_name_snapshot: str
    quantity: int
    notes: str | None
    base_price_snapshot: Decimal
    presentation_price_snapshot: Decimal
    addons_price_snapshot: Decimal
    unit_price_snapshot: Decimal
    line_total_snapshot: Decimal
    addon_options: tuple[OrderAddonOption, ...] = ()
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        try:
            validate_quantity(self.quantity)
            if self.notes != normalize_notes(self.notes):
                raise CartRuleError("Notes must be normalized")
        except CartRuleError:
            raise OrderRuleError("Invalid quantity or notes") from None
        text_value(self.product_name_snapshot, 150)
        text_value(self.presentation_name_snapshot, 150)
        for name in (
            "base_price_snapshot",
            "presentation_price_snapshot",
            "addons_price_snapshot",
            "unit_price_snapshot",
            "line_total_snapshot",
        ):
            money(getattr(self, name))
        if (
            self.unit_price_snapshot
            != self.presentation_price_snapshot + self.addons_price_snapshot
            or self.line_total_snapshot != self.unit_price_snapshot * self.quantity
            or self.addons_price_snapshot
            != sum(
                (option.additional_price_snapshot for option in self.addon_options),
                ZERO,
            )
            or len({option.product_addon_option_id for option in self.addon_options})
            != len(self.addon_options)
        ):
            raise OrderRuleError("Inconsistent item snapshots")


@dataclass(frozen=True, kw_only=True)
class LocalDetails:
    restaurant_table_id: UUID
    table_label_snapshot: str
    payment_choice: PaymentMethodType
    cash_confirmation_required_snapshot: bool


@dataclass(frozen=True, kw_only=True)
class PickupDetails:
    requested_pickup_at: datetime
    calculated_kitchen_release_at: datetime
    estimated_ready_at: datetime
    pickup_name_snapshot: str
    pickup_phone_snapshot: str

    def __post_init__(self) -> None:
        for value in (
            self.requested_pickup_at,
            self.calculated_kitchen_release_at,
            self.estimated_ready_at,
        ):
            aware(value)
        if (
            not self.calculated_kitchen_release_at
            <= self.estimated_ready_at
            <= self.requested_pickup_at
        ):
            raise OrderRuleError("Inconsistent pickup schedule")


@dataclass(frozen=True, kw_only=True)
class DeliveryDetails:
    customer_address_id: UUID | None
    delivery_zone_id: UUID
    delivery_zone_name_snapshot: str
    recipient_name_snapshot: str
    recipient_phone_snapshot: str
    address_line_snapshot: str
    reference_text_snapshot: str | None
    district_snapshot: str
    city_snapshot: str
    department_snapshot: str
    latitude_snapshot: Decimal | None
    longitude_snapshot: Decimal | None
    delivery_fee_snapshot: Decimal
    estimated_delivery_at: datetime

    def __post_init__(self) -> None:
        money(self.delivery_fee_snapshot)
        aware(self.estimated_delivery_at)


@dataclass(frozen=True, kw_only=True)
class ScheduleCalculation:
    queue_depth: int
    base_prep_minutes: int
    queue_delay_minutes: int
    buffer_minutes: int
    travel_minutes: int
    calculated_release_at: datetime | None
    estimated_ready_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for value in (
            self.queue_depth,
            self.base_prep_minutes,
            self.queue_delay_minutes,
            self.buffer_minutes,
            self.travel_minutes,
        ):
            if type(value) is not int or value < 0:
                raise OrderRuleError("Invalid schedule calculation")
        aware(self.estimated_ready_at)
        if self.calculated_release_at is not None:
            aware(self.calculated_release_at)


@dataclass(frozen=True, kw_only=True)
class StatusHistory:
    from_status: OrderStatus | None
    to_status: OrderStatus
    changed_by_user_id: UUID | None = None
    reason: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, kw_only=True)
class Order:
    source_cart_id: UUID
    customer_id: UUID
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    payment_method_type: PaymentMethodType
    payment_status: PaymentStatus
    customer_name_snapshot: str
    customer_phone_snapshot: str
    idempotency_key: str
    request_fingerprint: str
    subtotal: Decimal
    charges_total: Decimal
    discount_total: Decimal
    delivery_fee: Decimal
    total: Decimal
    items: tuple[OrderItem, ...]
    branch_settings_snapshot: BranchOrderSettings
    local_details: LocalDetails | None = None
    pickup_details: PickupDetails | None = None
    delivery_details: DeliveryDetails | None = None
    schedule_calculation: ScheduleCalculation | None = None
    history: tuple[StatusHistory, ...] = ()
    order_number: int | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not (
            isinstance(self.mode, OrderMode)
            and isinstance(self.status, OrderStatus)
            and isinstance(self.payment_method_type, PaymentMethodType)
            and isinstance(self.payment_status, PaymentStatus)
        ):
            raise OrderRuleError("Invalid order enum")
        if (
            self.mode != OrderMode.LOCAL
            and self.payment_method_type != PaymentMethodType.ONLINE
        ):
            raise OrderRuleError("Only local orders may use cash")
        if (
            self.payment_method_type == PaymentMethodType.ONLINE
            and self.payment_status == PaymentStatus.PENDING
            and self.status not in {OrderStatus.PENDING_PAYMENT, OrderStatus.CANCELLED}
        ):
            raise OrderRuleError("Online payment must precede order activation")
        if (
            self.local_details
            and self.local_details.payment_choice != self.payment_method_type
        ):
            raise OrderRuleError("Local payment snapshot does not match the order")
        detail = {
            OrderMode.LOCAL: self.local_details,
            OrderMode.PICKUP: self.pickup_details,
            OrderMode.DELIVERY: self.delivery_details,
        }
        if (
            detail[self.mode] is None
            or sum(value is not None for value in detail.values()) != 1
        ):
            raise OrderRuleError("Exactly one matching detail is required")
        for name in (
            "subtotal",
            "charges_total",
            "discount_total",
            "delivery_fee",
            "total",
        ):
            money(getattr(self, name))
        if (
            not self.items
            or self.subtotal
            != sum((item.line_total_snapshot for item in self.items), ZERO)
            or self.total != self.subtotal + self.charges_total - self.discount_total
            or self.delivery_fee > self.charges_total
            or (self.mode != OrderMode.DELIVERY and self.delivery_fee != ZERO)
        ):
            raise OrderRuleError("Inconsistent order totals")
        if (
            self.delivery_details
            and self.delivery_details.delivery_fee_snapshot != self.delivery_fee
        ):
            raise OrderRuleError("Delivery fee snapshot does not match the order")
        if self.branch_settings_snapshot.branch_id != self.branch_id:
            raise OrderRuleError("Settings must match order branch")
        text_value(self.customer_name_snapshot)
        text_value(self.customer_phone_snapshot, 20)
        if self.order_number is not None and self.order_number < 1:
            raise OrderRuleError("Invalid order number")
        from app.modules.orders.domain.transitions import allowed_statuses

        if self.status not in allowed_statuses(self.mode, self.payment_method_type):
            raise OrderRuleError("Status does not belong to order mode")
