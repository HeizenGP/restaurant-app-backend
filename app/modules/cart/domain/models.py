from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from app.shared.domain.time import utc_now

ZERO = Decimal("0.00")
MAX_QUANTITY = 10000
MAX_SNAPSHOT = Decimal("9999999999999999.99")


class CartRuleError(ValueError):
    """Pure cart invariant violation."""


class CartStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ABANDONED = "ABANDONED"


def snapshot_money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CartRuleError("Snapshot must be a finite Decimal")
    if value < 0 or value > MAX_SNAPSHOT or value != value.quantize(Decimal("0.01")):
        raise CartRuleError("Invalid monetary snapshot")
    return value.quantize(Decimal("0.01"))


def validate_quantity(quantity: int) -> None:
    if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
        raise CartRuleError("Invalid quantity")


def normalize_notes(notes: str | None) -> str | None:
    if notes is None:
        return None
    if not isinstance(notes, str) or len(notes) > 1000:
        raise CartRuleError("Invalid notes")
    if any(ord(char) < 32 and char not in {"\n", "\r", "\t"} for char in notes):
        raise CartRuleError("Invalid notes")
    return notes.strip() or None


@dataclass(frozen=True, kw_only=True)
class Cart:
    customer_id: UUID
    branch_id: UUID
    id: UUID = field(default_factory=uuid4)
    status: CartStatus = CartStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.status not in {CartStatus.ACTIVE, CartStatus.ABANDONED}:
            raise CartRuleError("Invalid cart status")


@dataclass(frozen=True, kw_only=True)
class SelectedOption:
    cart_item_id: UUID
    product_addon_id: UUID
    product_addon_option_id: UUID
    additional_price_snapshot: Decimal
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        snapshot_money(self.additional_price_snapshot)


@dataclass(frozen=True, kw_only=True)
class CartItem:
    cart_id: UUID
    product_id: UUID
    presentation_id: UUID
    quantity: int
    notes: str | None
    base_price_snapshot: Decimal
    presentation_price_snapshot: Decimal
    addons_price_snapshot: Decimal
    unit_price_snapshot: Decimal
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    selected_options: tuple[SelectedOption, ...] = ()

    def __post_init__(self) -> None:
        validate_quantity(self.quantity)
        if self.notes != normalize_notes(self.notes):
            raise CartRuleError("Notes must be normalized")
        for value in (
            self.base_price_snapshot,
            self.presentation_price_snapshot,
            self.addons_price_snapshot,
            self.unit_price_snapshot,
        ):
            snapshot_money(value)
        if (
            self.unit_price_snapshot
            != self.presentation_price_snapshot + self.addons_price_snapshot
        ):
            raise CartRuleError("Inconsistent unit snapshot")
        ids = [option.product_addon_option_id for option in self.selected_options]
        if len(set(ids)) != len(ids) or any(
            option.cart_item_id != self.id for option in self.selected_options
        ):
            raise CartRuleError("Invalid selected options")
        if (
            sum(
                (option.additional_price_snapshot for option in self.selected_options),
                ZERO,
            )
            != self.addons_price_snapshot
        ):
            raise CartRuleError("Inconsistent addon snapshots")

    @property
    def line_total(self) -> Decimal:
        return (self.unit_price_snapshot * self.quantity).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class CartTotals:
    subtotal: Decimal
    charges_total: Decimal
    discount_total: Decimal
    total: Decimal
    item_count: int

    @classmethod
    def from_items(cls, items: tuple[CartItem, ...]) -> "CartTotals":
        subtotal = sum((item.line_total for item in items), ZERO)
        return cls(subtotal, ZERO, ZERO, subtotal, sum(item.quantity for item in items))
