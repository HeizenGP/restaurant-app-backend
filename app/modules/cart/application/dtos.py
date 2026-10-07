from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.cart.domain.models import Cart, CartItem, CartStatus, CartTotals


@dataclass(frozen=True)
class AddonSelection:
    addon_id: UUID
    option_ids: tuple[UUID, ...]


@dataclass(frozen=True, kw_only=True)
class ItemCreate:
    product_id: UUID
    presentation_id: UUID
    quantity: int
    notes: str | None = None
    addons: tuple[AddonSelection, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ItemUpdate:
    provided_fields: frozenset[str]
    quantity: int | None = None
    presentation_id: UUID | None = None
    notes: str | None = None
    addons: tuple[AddonSelection, ...] | None = None


@dataclass(frozen=True)
class ValidatedOption:
    addon_id: UUID
    option_id: UUID
    additional_price: Decimal


@dataclass(frozen=True, kw_only=True)
class ValidatedSelection:
    product_id: UUID
    branch_id: UUID
    presentation_id: UUID
    base_price: Decimal
    presentation_price: Decimal
    addons_price: Decimal
    unit_price: Decimal
    allows_notes: bool
    options: tuple[ValidatedOption, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CartView:
    id: UUID
    branch_id: UUID
    status: CartStatus
    items: tuple[CartItem, ...]
    subtotal: Decimal
    charges_total: Decimal
    discount_total: Decimal
    total: Decimal
    item_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_cart(cls, cart: Cart, items: tuple[CartItem, ...]) -> "CartView":
        totals = CartTotals.from_items(items)
        return cls(
            id=cart.id,
            branch_id=cart.branch_id,
            status=cart.status,
            items=items,
            subtotal=totals.subtotal,
            charges_total=totals.charges_total,
            discount_total=totals.discount_total,
            total=totals.total,
            item_count=totals.item_count,
            created_at=cart.created_at,
            updated_at=cart.updated_at,
        )
