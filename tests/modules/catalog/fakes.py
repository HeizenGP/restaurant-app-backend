from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.catalog.application.dtos import (
    AddonCreate,
    BranchProductConfig,
    CatalogChanges,
    CategoryCreate,
    ImageCreate,
    OptionCreate,
    PresentationCreate,
    ProductAggregate,
    ProductCreate,
)
from app.modules.catalog.application.errors import CatalogConflictError
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.domain.models import (
    BranchProduct,
    Category,
    Product,
    ProductAddon,
    ProductAddonOption,
    ProductImage,
    ProductPresentation,
)
from app.shared.application.audit import AuditRecord
from app.shared.domain.time import utc_now


def ordered(rows: list) -> list:
    return sorted(
        rows,
        key=lambda row: (
            row.sort_order,
            getattr(row, "name", "").casefold(),
            str(row.id),
        ),
    )


class MemoryCatalogRepository:
    """Explicit catalog test double with shared transactional audit snapshots."""

    def __init__(self) -> None:
        self.categories: dict[UUID, Category] = {}
        self.products: dict[UUID, Product] = {}
        self.images: dict[UUID, ProductImage] = {}
        self.presentations: dict[UUID, ProductPresentation] = {}
        self.addons: dict[UUID, ProductAddon] = {}
        self.options: dict[UUID, ProductAddonOption] = {}
        self.branch_products: dict[tuple[UUID, UUID], BranchProduct] = {}
        self.branches: set[UUID] = set()
        self.events: list[AuditRecord] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self._snapshot = self._state()

    def _state(self) -> tuple:
        return deepcopy(
            (
                self.categories,
                self.products,
                self.images,
                self.presentations,
                self.addons,
                self.options,
                self.branch_products,
                self.events,
            )
        )

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("simulated catalog commit failure")
        self.commits += 1
        self._snapshot = self._state()

    async def rollback(self) -> None:
        self.rollbacks += 1
        (
            self.categories,
            self.products,
            self.images,
            self.presentations,
            self.addons,
            self.options,
            self.branch_products,
            self.events,
        ) = deepcopy(self._snapshot)

    async def branch_is_active(self, branch_id: UUID) -> bool:
        return branch_id in self.branches

    async def list_categories(self) -> list[Category]:
        return ordered([c for c in self.categories.values() if c.deleted_at is None])

    async def list_products(self) -> list[Product]:
        return ordered([p for p in self.products.values() if p.deleted_at is None])

    async def get_category(
        self, category_id: UUID, *, lock: bool = False
    ) -> Category | None:
        category = self.categories.get(category_id)
        return (
            category if category is not None and category.deleted_at is None else None
        )

    async def get_product(
        self, product_id: UUID, *, lock: bool = False
    ) -> Product | None:
        product = self.products.get(product_id)
        return product if product is not None and product.deleted_at is None else None

    async def category_has_active_products(self, category_id: UUID) -> bool:
        return any(
            p.category_id == category_id and p.is_active and p.deleted_at is None
            for p in self.products.values()
        )

    def aggregate(self, product: Product, branch_id: UUID | None) -> ProductAggregate:
        override = self.branch_products.get((branch_id, product.id))
        addons = ordered(
            [
                a
                for a in self.addons.values()
                if a.product_id == product.id and a.deleted_at is None
            ]
        )
        return ProductAggregate(
            product=product,
            category=self.categories[product.category_id],
            override=BranchProductConfig(
                is_available=override.is_available,
                price_override=override.price_override,
            )
            if override
            else None,
            images=tuple(
                ordered(
                    [
                        i
                        for i in self.images.values()
                        if i.product_id == product.id and i.deleted_at is None
                    ]
                )
            ),
            presentations=tuple(
                ordered(
                    [
                        p
                        for p in self.presentations.values()
                        if p.product_id == product.id and p.deleted_at is None
                    ]
                )
            ),
            addons=tuple(addons),
            options=tuple(
                ordered(
                    [
                        o
                        for o in self.options.values()
                        if o.product_addon_id in {a.id for a in addons}
                        and o.deleted_at is None
                    ]
                )
            ),
        )

    async def public_products(
        self, branch_id: UUID, product_id: UUID | None = None
    ) -> list[ProductAggregate]:
        rows = sorted(
            self.products.values(),
            key=lambda p: (
                self.categories[p.category_id].sort_order,
                self.categories[p.category_id].name.casefold(),
                str(p.category_id),
                p.sort_order,
                p.name.casefold(),
                str(p.id),
            ),
        )
        return [
            self.aggregate(product, branch_id)
            for product in rows
            if product_id is None or product.id == product_id
        ]

    async def admin_product(self, product_id: UUID) -> ProductAggregate | None:
        product = await self.get_product(product_id)
        return None if product is None else self.aggregate(product, None)

    async def create_category(self, command: CategoryCreate) -> Category:
        if any(c.slug == command.slug for c in self.categories.values()):
            raise CatalogConflictError("CATEGORY_SLUG_CONFLICT")
        if any(
            c.name.casefold() == command.name.casefold()
            for c in self.categories.values()
        ):
            raise CatalogConflictError("CATEGORY_NAME_CONFLICT")
        entity = Category(**asdict(command))
        self.categories[entity.id] = entity
        return entity

    async def update_category(
        self, category: Category, changes: CatalogChanges
    ) -> Category:
        if "slug" in changes.values and any(
            row.id != category.id and row.slug == changes.values["slug"]
            for row in self.categories.values()
        ):
            raise CatalogConflictError("CATEGORY_SLUG_CONFLICT")
        entity = replace(category, **changes.values, updated_at=utc_now())
        self.categories[entity.id] = entity
        return entity

    async def archive_category(self, category: Category) -> Category:
        entity = replace(category, deleted_at=utc_now(), updated_at=utc_now())
        self.categories[entity.id] = entity
        return entity

    async def create_product(self, command: ProductCreate) -> Product:
        if any(p.slug == command.slug for p in self.products.values()):
            raise CatalogConflictError("PRODUCT_SLUG_CONFLICT")
        entity = Product(**asdict(command))
        self.products[entity.id] = entity
        return entity

    async def update_product(
        self, product: Product, changes: CatalogChanges
    ) -> Product:
        if "slug" in changes.values and any(
            row.id != product.id and row.slug == changes.values["slug"]
            for row in self.products.values()
        ):
            raise CatalogConflictError("PRODUCT_SLUG_CONFLICT")
        entity = replace(product, **changes.values, updated_at=utc_now())
        self.products[entity.id] = entity
        return entity

    async def archive_product(self, product: Product) -> Product:
        entity = replace(product, deleted_at=utc_now(), updated_at=utc_now())
        self.products[entity.id] = entity
        return entity

    async def get_image(self, product_id: UUID, image_id: UUID) -> ProductImage | None:
        entity = self.images.get(image_id)
        return (
            entity
            if entity is not None
            and entity.product_id == product_id
            and entity.deleted_at is None
            else None
        )

    async def create_image(
        self, product_id: UUID, command: ImageCreate
    ) -> ProductImage:
        if command.is_primary:
            self._clear_primary(product_id)
        entity = ProductImage(product_id=product_id, **asdict(command))
        self.images[entity.id] = entity
        return entity

    async def update_image(
        self, image: ProductImage, changes: CatalogChanges
    ) -> ProductImage:
        if changes.values.get("is_primary", image.is_primary):
            self._clear_primary(image.product_id, image.id)
        entity = replace(image, **changes.values, updated_at=utc_now())
        self.images[entity.id] = entity
        return entity

    async def archive_image(self, image: ProductImage) -> ProductImage:
        entity = replace(image, deleted_at=utc_now(), updated_at=utc_now())
        self.images[entity.id] = entity
        return entity

    async def get_presentation(
        self, product_id: UUID, presentation_id: UUID
    ) -> ProductPresentation | None:
        entity = self.presentations.get(presentation_id)
        return (
            entity
            if entity is not None
            and entity.product_id == product_id
            and entity.deleted_at is None
            else None
        )

    async def create_presentation(
        self, product_id: UUID, command: PresentationCreate
    ) -> ProductPresentation:
        if command.is_default and command.is_active:
            self._clear_default(product_id)
        entity = ProductPresentation(product_id=product_id, **asdict(command))
        self.presentations[entity.id] = entity
        return entity

    async def update_presentation(
        self, presentation: ProductPresentation, changes: CatalogChanges
    ) -> ProductPresentation:
        if changes.values.get(
            "is_default", presentation.is_default
        ) and changes.values.get("is_active", presentation.is_active):
            self._clear_default(presentation.product_id, presentation.id)
        entity = replace(presentation, **changes.values, updated_at=utc_now())
        self.presentations[entity.id] = entity
        return entity

    async def archive_presentation(
        self, presentation: ProductPresentation
    ) -> ProductPresentation:
        entity = replace(presentation, deleted_at=utc_now(), updated_at=utc_now())
        self.presentations[entity.id] = entity
        return entity

    async def get_addon(self, product_id: UUID, addon_id: UUID) -> ProductAddon | None:
        entity = self.addons.get(addon_id)
        return (
            entity
            if entity is not None
            and entity.product_id == product_id
            and entity.deleted_at is None
            else None
        )

    async def create_addon(
        self, product_id: UUID, command: AddonCreate
    ) -> ProductAddon:
        entity = ProductAddon(product_id=product_id, **asdict(command))
        self.addons[entity.id] = entity
        return entity

    async def update_addon(
        self, addon: ProductAddon, changes: CatalogChanges
    ) -> ProductAddon:
        entity = replace(addon, **changes.values, updated_at=utc_now())
        self.addons[entity.id] = entity
        return entity

    async def archive_addon(self, addon: ProductAddon) -> ProductAddon:
        entity = replace(addon, deleted_at=utc_now(), updated_at=utc_now())
        self.addons[entity.id] = entity
        return entity

    async def get_option(
        self, addon_id: UUID, option_id: UUID
    ) -> ProductAddonOption | None:
        entity = self.options.get(option_id)
        return (
            entity
            if entity is not None
            and entity.product_addon_id == addon_id
            and entity.deleted_at is None
            else None
        )

    async def create_option(
        self, addon_id: UUID, command: OptionCreate
    ) -> ProductAddonOption:
        entity = ProductAddonOption(product_addon_id=addon_id, **asdict(command))
        self.options[entity.id] = entity
        return entity

    async def update_option(
        self, option: ProductAddonOption, changes: CatalogChanges
    ) -> ProductAddonOption:
        entity = replace(option, **changes.values, updated_at=utc_now())
        self.options[entity.id] = entity
        return entity

    async def archive_option(self, option: ProductAddonOption) -> ProductAddonOption:
        entity = replace(option, deleted_at=utc_now(), updated_at=utc_now())
        self.options[entity.id] = entity
        return entity

    def _clear_primary(self, product_id: UUID, excluding: UUID | None = None) -> None:
        for key, image in list(self.images.items()):
            if (
                image.product_id == product_id
                and image.id != excluding
                and image.deleted_at is None
                and image.is_primary
            ):
                self.images[key] = replace(image, is_primary=False)

    def _clear_default(self, product_id: UUID, excluding: UUID | None = None) -> None:
        for key, presentation in list(self.presentations.items()):
            if (
                presentation.product_id == product_id
                and presentation.id != excluding
                and presentation.is_active
                and presentation.deleted_at is None
                and presentation.is_default
            ):
                self.presentations[key] = replace(presentation, is_default=False)

    async def get_branch_product(
        self, branch_id: UUID, product_id: UUID
    ) -> BranchProduct | None:
        return self.branch_products.get((branch_id, product_id))

    async def upsert_branch_product(
        self, branch_id: UUID, product_id: UUID, command: BranchProductConfig
    ) -> BranchProduct:
        existing = self.branch_products.get((branch_id, product_id))
        entity = (
            replace(existing, **asdict(command), updated_at=utc_now())
            if existing
            else BranchProduct(
                branch_id=branch_id, product_id=product_id, **asdict(command)
            )
        )
        self.branch_products[(branch_id, product_id)] = entity
        return entity


@dataclass
class Grant:
    branch_id: UUID
    role: str = "ADMIN"
    permissions: tuple[str, ...] = ("CATALOG_MANAGE",)
    active: bool = True
    ended: bool = False


class MemoryCatalogAuthorization:
    def __init__(self, repository: MemoryCatalogRepository) -> None:
        self.repository = repository
        self.grants: dict[UUID, list[Grant]] = {}
        self.inactive_users: set[UUID] = set()

    async def can_manage(self, user_id: UUID, branch_id: UUID | None) -> bool:
        if user_id in self.inactive_users:
            return False
        return any(
            grant.active
            and not grant.ended
            and grant.branch_id in self.repository.branches
            and "CATALOG_MANAGE" in grant.permissions
            and (
                grant.role == "ADMIN"
                if branch_id is None
                else grant.branch_id == branch_id
            )
            for grant in self.grants.get(user_id, [])
        )


class MemoryAuditRecorder:
    def __init__(self, repository: MemoryCatalogRepository) -> None:
        self.repository = repository
        self.fail_record = False

    async def record(self, event: AuditRecord) -> None:
        if self.fail_record:
            raise RuntimeError("simulated audit insert failure")
        self.repository.events.append(event)


async def seed(service: CatalogService, admin: Principal) -> tuple:
    category = await service.create_category(
        admin, CategoryCreate(name="Arroces", slug="arroces")
    )
    product = await service.create_product(
        admin,
        ProductCreate(
            category_id=category.id,
            name="Aeropuerto",
            slug="aeropuerto",
            base_price=Decimal("20.00"),
        ),
    )
    personal = await service.create_presentation(
        admin,
        product.id,
        PresentationCreate(
            name="Individual", price_delta=Decimal("0.00"), is_default=True
        ),
    )
    familiar = await service.create_presentation(
        admin,
        product.id,
        PresentationCreate(
            name="Compartido", price_delta=Decimal("15.00"), sort_order=1
        ),
    )
    addon = await service.create_addon(
        admin, product.id, AddonCreate(name="Extras", max_select=2)
    )
    free = await service.create_option(
        admin,
        product.id,
        addon.id,
        OptionCreate(name="Salsa", additional_price=Decimal("0.00")),
    )
    paid = await service.create_option(
        admin,
        product.id,
        addon.id,
        OptionCreate(name="Wantan", additional_price=Decimal("3.50")),
    )
    return category, product, personal, familiar, addon, free, paid
