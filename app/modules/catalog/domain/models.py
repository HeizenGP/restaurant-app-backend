import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from app.shared.domain.time import utc_now

MAX_MONEY = Decimal("9999999999.99")


class CatalogRuleError(ValueError):
    """Pure-domain invariant violation."""


class ProductState(StrEnum):
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"
    INACTIVE = "INACTIVE"
    ARCHIVED = "ARCHIVED"


def money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CatalogRuleError("Money must be a finite Decimal")
    if value < 0 or value > MAX_MONEY or value != value.quantize(Decimal("0.01")):
        raise CatalogRuleError("Money must be nonnegative with at most two decimals")
    return value.quantize(Decimal("0.01"))


def effective_base_price(base: Decimal, override: Decimal | None) -> Decimal:
    return money(base if override is None else override)


def presentation_price(base: Decimal, delta: Decimal) -> Decimal:
    return money(base) + money(delta)


def validate_selection_limits(minimum: int, maximum: int) -> None:
    if minimum < 0 or maximum < 1 or minimum > maximum:
        raise CatalogRuleError("Invalid addon selection limits")


@dataclass(frozen=True, kw_only=True)
class CatalogEntity:
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        name = getattr(self, "name", None)
        if name is not None and (
            not name.strip() or name != name.strip() or len(name) > 150
        ):
            raise CatalogRuleError("Invalid catalog name")
        if getattr(self, "sort_order", 0) < 0:
            raise CatalogRuleError("Negative sort order")
        slug = getattr(self, "slug", None)
        if slug is not None and (
            len(slug) > 160 or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None
        ):
            raise CatalogRuleError("Invalid catalog slug")
        for field_name in ("base_price", "price_delta", "additional_price"):
            value = getattr(self, field_name, None)
            if value is not None:
                money(value)


@dataclass(frozen=True, kw_only=True)
class Category(CatalogEntity):
    name: str
    slug: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class Product(CatalogEntity):
    category_id: UUID
    name: str
    slug: str
    description: str | None
    base_price: Decimal
    allows_notes: bool = True
    sort_order: int = 0
    is_active: bool = True

    def state(self, is_available: bool) -> ProductState:
        if self.deleted_at is not None:
            return ProductState.ARCHIVED
        if not self.is_active:
            return ProductState.INACTIVE
        return ProductState.AVAILABLE if is_available else ProductState.SOLD_OUT


@dataclass(frozen=True, kw_only=True)
class ProductImage(CatalogEntity):
    product_id: UUID
    url: str
    alt_text: str | None = None
    sort_order: int = 0
    is_primary: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        url = urlsplit(self.url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or len(self.url) > 2048
        ):
            raise CatalogRuleError("Invalid image URL")


@dataclass(frozen=True, kw_only=True)
class ProductPresentation(CatalogEntity):
    product_id: UUID
    name: str
    price_delta: Decimal
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0


@dataclass(frozen=True, kw_only=True)
class ProductAddon(CatalogEntity):
    product_id: UUID
    name: str
    is_required: bool = False
    min_select: int = 0
    max_select: int = 1
    sort_order: int = 0
    is_active: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        validate_selection_limits(self.min_select, self.max_select)


@dataclass(frozen=True, kw_only=True)
class ProductAddonOption(CatalogEntity):
    product_addon_id: UUID
    name: str
    additional_price: Decimal
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class BranchProduct:
    id: UUID = field(default_factory=uuid4)
    branch_id: UUID
    product_id: UUID
    is_available: bool = True
    price_override: Decimal | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
