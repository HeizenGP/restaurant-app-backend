from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.modules.catalog.domain.models import (
    Category,
    Product,
    ProductAddon,
    ProductAddonOption,
    ProductImage,
    ProductPresentation,
    ProductState,
)

CatalogValue = str | int | bool | Decimal | UUID | None


@dataclass(frozen=True, kw_only=True)
class CategoryCreate:
    name: str
    slug: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class ProductCreate:
    category_id: UUID
    name: str
    slug: str
    base_price: Decimal
    description: str | None = None
    allows_notes: bool = True
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class ImageCreate:
    url: str
    alt_text: str | None = None
    sort_order: int = 0
    is_primary: bool = False


@dataclass(frozen=True, kw_only=True)
class PresentationCreate:
    name: str
    price_delta: Decimal
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0


@dataclass(frozen=True, kw_only=True)
class AddonCreate:
    name: str
    is_required: bool = False
    min_select: int = 0
    max_select: int = 1
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True, kw_only=True)
class OptionCreate:
    name: str
    additional_price: Decimal
    sort_order: int = 0
    is_active: bool = True


@dataclass(frozen=True)
class CatalogChanges:
    values: dict[str, CatalogValue]


@dataclass(frozen=True)
class BranchProductConfig:
    is_available: bool
    price_override: Decimal | None


@dataclass(frozen=True, kw_only=True)
class ProductAggregate:
    product: Product
    category: Category
    override: BranchProductConfig | None = None
    images: tuple[ProductImage, ...] = ()
    presentations: tuple[ProductPresentation, ...] = ()
    addons: tuple[ProductAddon, ...] = ()
    options: tuple[ProductAddonOption, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PublicPresentation:
    id: UUID
    name: str
    price_delta: Decimal
    effective_price: Decimal
    is_default: bool


@dataclass(frozen=True, kw_only=True)
class PublicOption:
    id: UUID
    name: str
    additional_price: Decimal


@dataclass(frozen=True, kw_only=True)
class PublicAddon:
    id: UUID
    name: str
    is_required: bool
    min_select: int
    max_select: int
    options: tuple[PublicOption, ...]


@dataclass(frozen=True, kw_only=True)
class CategorySummary:
    id: UUID
    name: str
    slug: str


@dataclass(frozen=True, kw_only=True)
class PublicProduct:
    id: UUID
    category: CategorySummary
    name: str
    slug: str
    description: str | None
    effective_base_price: Decimal
    is_available: bool
    state: ProductState
    allows_notes: bool
    primary_image: ProductImage | None
    default_presentation: PublicPresentation | None
    images: tuple[ProductImage, ...]
    presentations: tuple[PublicPresentation, ...]
    addons: tuple[PublicAddon, ...]


@dataclass(frozen=True, kw_only=True)
class MenuCategory:
    id: UUID
    name: str
    slug: str
    description: str | None
    products: tuple[PublicProduct, ...]


@dataclass(frozen=True)
class AddonSelection:
    addon_id: UUID
    option_ids: tuple[UUID, ...]


@dataclass(frozen=True, kw_only=True)
class ProductSelection:
    """Catalog validation result, not a persisted cart or order."""

    product_id: UUID
    branch_id: UUID
    presentation_id: UUID
    base_price: Decimal
    presentation_price: Decimal
    addons_price: Decimal
    unit_price: Decimal
    allows_notes: bool
