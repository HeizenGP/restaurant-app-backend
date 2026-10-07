from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.catalog.application.dtos import (
    AddonCreate,
    AddonSelection,
    BranchProductConfig,
    CatalogChanges,
    CategoryCreate,
    CategorySummary,
    ImageCreate,
    MenuCategory,
    OptionCreate,
    PresentationCreate,
    ProductAggregate,
    ProductCreate,
    ProductSelection,
    PublicAddon,
    PublicOption,
    PublicPresentation,
    PublicProduct,
    SelectedAddonOption,
)
from app.modules.catalog.application.errors import (
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogPermissionDeniedError,
    InvalidCatalogDataError,
    InvalidSelectionError,
    ProductNotAvailableError,
)
from app.modules.catalog.application.ports import (
    CatalogAuthorization,
    CatalogRepository,
)
from app.modules.catalog.domain.models import (
    BranchProduct,
    CatalogEntity,
    CatalogRuleError,
    Category,
    Product,
    ProductAddon,
    ProductAddonOption,
    ProductImage,
    ProductPresentation,
    effective_base_price,
    money,
    presentation_price,
)
from app.shared.application.audit import AuditRecord, AuditRecorder, AuditState

Record = CatalogEntity | BranchProduct


def snapshot(entity: Record | None) -> AuditState | None:
    if entity is None:
        return None
    result: AuditState = {}
    for key, value in asdict(entity).items():
        if isinstance(value, (UUID, Decimal)):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


class CatalogService:
    def __init__(
        self,
        repository: CatalogRepository,
        authorization: CatalogAuthorization,
        audit: AuditRecorder,
    ) -> None:
        self._repository = repository
        self._authorization = authorization
        self._audit = audit

    async def _require_branch(self, branch_id: UUID) -> None:
        if not await self._repository.branch_is_active(branch_id):
            raise CatalogNotFoundError("BRANCH")

    async def require_manage(
        self, principal: Principal, branch_id: UUID | None = None
    ) -> UUID:
        if (
            principal.principal_type is not PrincipalType.REGISTERED
            or principal.user_id is None
        ):
            raise CatalogPermissionDeniedError()
        if branch_id is not None:
            await self._require_branch(branch_id)
        if not await self._authorization.can_manage(principal.user_id, branch_id):
            raise CatalogPermissionDeniedError()
        return principal.user_id

    @asynccontextmanager
    async def _write(
        self, principal: Principal, branch_id: UUID | None = None
    ) -> AsyncIterator[UUID]:
        actor = await self.require_manage(principal, branch_id)
        try:
            yield actor
            await self._repository.commit()
        except CatalogRuleError:
            await self._repository.rollback()
            raise InvalidCatalogDataError() from None
        except Exception:
            await self._repository.rollback()
            raise

    async def _record(
        self,
        actor: UUID,
        action: str,
        before: Record | None,
        after: Record,
        branch_id: UUID | None = None,
    ) -> None:
        await self._audit.record(
            AuditRecord(
                actor_user_id=actor,
                branch_id=branch_id,
                action=action,
                entity_type=action.rsplit("_", 1)[0],
                entity_id=after.id,
                before_state=snapshot(before),
                after_state=snapshot(after),
            )
        )

    async def _category(self, category_id: UUID, *, lock: bool = False) -> Category:
        entity = await self._repository.get_category(category_id, lock=lock)
        if entity is None:
            raise CatalogNotFoundError("CATEGORY")
        return entity

    async def _product(self, product_id: UUID, *, lock: bool = False) -> Product:
        entity = await self._repository.get_product(product_id, lock=lock)
        if entity is None:
            raise CatalogNotFoundError("PRODUCT")
        return entity

    @staticmethod
    def _changes(
        before: CatalogEntity, changes: CatalogChanges, allowed: set[str]
    ) -> None:
        if not changes.values or not changes.values.keys() <= allowed:
            raise InvalidCatalogDataError()
        replace(before, **changes.values)

    async def menu(self, branch_id: UUID) -> list[MenuCategory]:
        await self._require_branch(branch_id)
        records = await self._repository.public_products(branch_id)
        grouped: dict[UUID, list[PublicProduct]] = defaultdict(list)
        categories: dict[UUID, Category] = {}
        for aggregate in records:
            product = self._public(aggregate)
            if product is not None:
                categories[aggregate.category.id] = aggregate.category
                grouped[aggregate.category.id].append(product)
        return [
            MenuCategory(
                id=category.id,
                name=category.name,
                slug=category.slug,
                description=category.description,
                products=tuple(grouped[category.id]),
            )
            for category in categories.values()
        ]

    async def product_detail(self, branch_id: UUID, product_id: UUID) -> PublicProduct:
        await self._require_branch(branch_id)
        records = await self._repository.public_products(branch_id, product_id)
        product = self._public(records[0]) if records else None
        if product is None:
            raise CatalogNotFoundError("PRODUCT")
        return product

    @staticmethod
    def _public(aggregate: ProductAggregate) -> PublicProduct | None:
        product, category = aggregate.product, aggregate.category
        presentations = tuple(
            p
            for p in aggregate.presentations
            if p.product_id == product.id and p.is_active and p.deleted_at is None
        )
        if (
            not product.is_active
            or product.deleted_at is not None
            or not category.is_active
            or category.deleted_at is not None
            or not presentations
        ):
            return None
        base = effective_base_price(
            product.base_price,
            aggregate.override.price_override if aggregate.override else None,
        )
        available = aggregate.override.is_available if aggregate.override else True
        public_presentations = tuple(
            PublicPresentation(
                id=p.id,
                name=p.name,
                price_delta=p.price_delta,
                effective_price=presentation_price(base, p.price_delta),
                is_default=p.is_default,
            )
            for p in presentations
        )
        images = tuple(
            i
            for i in aggregate.images
            if i.product_id == product.id and i.deleted_at is None
        )
        addons = tuple(
            PublicAddon(
                id=addon.id,
                name=addon.name,
                is_required=addon.is_required,
                min_select=addon.min_select,
                max_select=addon.max_select,
                options=tuple(
                    PublicOption(
                        id=option.id,
                        name=option.name,
                        additional_price=option.additional_price,
                    )
                    for option in aggregate.options
                    if option.product_addon_id == addon.id
                    and option.is_active
                    and option.deleted_at is None
                ),
            )
            for addon in aggregate.addons
            if addon.product_id == product.id
            and addon.is_active
            and addon.deleted_at is None
        )
        return PublicProduct(
            id=product.id,
            category=CategorySummary(
                id=category.id, name=category.name, slug=category.slug
            ),
            name=product.name,
            slug=product.slug,
            description=product.description,
            effective_base_price=base,
            is_available=available,
            state=product.state(available),
            allows_notes=product.allows_notes,
            primary_image=next((image for image in images if image.is_primary), None),
            default_presentation=next(
                (p for p in public_presentations if p.is_default), None
            ),
            images=images,
            presentations=public_presentations,
            addons=addons,
        )

    async def validate_selection(
        self,
        branch_id: UUID,
        product_id: UUID,
        presentation_id: UUID,
        addons: tuple[AddonSelection, ...] = (),
        notes: str | None = None,
    ) -> ProductSelection:
        """Reusable internal pricing/ownership validation; creates no cart/order."""
        product = await self.product_detail(branch_id, product_id)
        return self.validate_product_selection(
            branch_id, product, presentation_id, addons, notes
        )

    @staticmethod
    def validate_product_selection(
        branch_id: UUID,
        product: PublicProduct,
        presentation_id: UUID,
        addons: tuple[AddonSelection, ...] = (),
        notes: str | None = None,
    ) -> ProductSelection:
        """One pricing policy for ordinary Cart and batched, locked checkout."""
        if not product.is_available:
            raise ProductNotAvailableError()
        presentation = next(
            (p for p in product.presentations if p.id == presentation_id), None
        )
        if presentation is None or (notes and not product.allows_notes):
            raise InvalidSelectionError()
        chosen = {selection.addon_id: selection.option_ids for selection in addons}
        if len(chosen) != len(addons) or not chosen.keys() <= {
            addon.id for addon in product.addons
        }:
            raise InvalidSelectionError()
        addon_price = Decimal("0.00")
        selected_options: list[SelectedAddonOption] = []
        for addon in product.addons:
            selected = chosen.get(addon.id, ())
            minimum = max(addon.min_select, 1 if addon.is_required else 0)
            if (
                len(set(selected)) != len(selected)
                or not minimum <= len(selected) <= addon.max_select
            ):
                raise InvalidSelectionError()
            allowed = {option.id: option for option in addon.options}
            if not set(selected) <= allowed.keys():
                raise InvalidSelectionError()
            selected_options.extend(
                SelectedAddonOption(
                    addon_id=addon.id,
                    option_id=option_id,
                    additional_price=allowed[option_id].additional_price,
                    addon_name=addon.name,
                    option_name=allowed[option_id].name,
                )
                for option_id in selected
            )
            addon_price += sum(
                (allowed[option_id].additional_price for option_id in selected),
                Decimal("0.00"),
            )
        return ProductSelection(
            product_id=product.id,
            branch_id=branch_id,
            presentation_id=presentation.id,
            base_price=product.effective_base_price,
            presentation_price=presentation.effective_price,
            addons_price=addon_price,
            unit_price=presentation.effective_price + addon_price,
            allows_notes=product.allows_notes,
            selected_options=tuple(selected_options),
            product_name=product.name,
            presentation_name=presentation.name,
        )

    async def list_categories(self, principal: Principal) -> list[Category]:
        await self.require_manage(principal)
        return await self._repository.list_categories()

    async def list_products(self, principal: Principal) -> list[Product]:
        await self.require_manage(principal)
        return await self._repository.list_products()

    async def admin_product(
        self, principal: Principal, product_id: UUID
    ) -> ProductAggregate:
        await self.require_manage(principal)
        product = await self._repository.admin_product(product_id)
        if product is None:
            raise CatalogNotFoundError("PRODUCT")
        return product

    async def create_category(
        self, principal: Principal, command: CategoryCreate
    ) -> Category:
        async with self._write(principal) as actor:
            Category(**asdict(command))
            entity = await self._repository.create_category(command)
            await self._record(actor, "CATEGORY_CREATED", None, entity)
            return entity

    async def update_category(
        self, principal: Principal, category_id: UUID, changes: CatalogChanges
    ) -> Category:
        async with self._write(principal) as actor:
            before = await self._category(category_id, lock=True)
            self._changes(
                before,
                changes,
                {"name", "slug", "description", "sort_order", "is_active"},
            )
            entity = await self._repository.update_category(before, changes)
            await self._record(actor, "CATEGORY_UPDATED", before, entity)
            return entity

    async def archive_category(self, principal: Principal, category_id: UUID) -> None:
        async with self._write(principal) as actor:
            before = await self._category(category_id, lock=True)
            if await self._repository.category_has_active_products(category_id):
                raise CatalogConflictError("CATEGORY_HAS_ACTIVE_PRODUCTS")
            entity = await self._repository.archive_category(before)
            await self._record(actor, "CATEGORY_ARCHIVED", before, entity)

    async def create_product(
        self, principal: Principal, command: ProductCreate
    ) -> Product:
        async with self._write(principal) as actor:
            await self._category(command.category_id, lock=True)
            Product(**asdict(command))
            entity = await self._repository.create_product(command)
            await self._record(actor, "PRODUCT_CREATED", None, entity)
            return entity

    async def update_product(
        self, principal: Principal, product_id: UUID, changes: CatalogChanges
    ) -> Product:
        async with self._write(principal) as actor:
            snapshot_product = await self._product(product_id)
            category_id = changes.values.get(
                "category_id", snapshot_product.category_id
            )
            if not isinstance(category_id, UUID):
                raise InvalidCatalogDataError()
            await self._category(category_id, lock=True)
            before = await self._product(product_id, lock=True)
            if before.category_id != snapshot_product.category_id:
                raise CatalogConflictError()
            self._changes(
                before,
                changes,
                {
                    "category_id",
                    "name",
                    "slug",
                    "description",
                    "base_price",
                    "allows_notes",
                    "sort_order",
                    "is_active",
                },
            )
            entity = await self._repository.update_product(before, changes)
            await self._record(actor, "PRODUCT_UPDATED", before, entity)
            return entity

    async def archive_product(self, principal: Principal, product_id: UUID) -> None:
        async with self._write(principal) as actor:
            before = await self._product(product_id, lock=True)
            entity = await self._repository.archive_product(before)
            await self._record(actor, "PRODUCT_ARCHIVED", before, entity)

    async def create_image(
        self, principal: Principal, product_id: UUID, command: ImageCreate
    ) -> ProductImage:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            ProductImage(product_id=product_id, **asdict(command))
            entity = await self._repository.create_image(product_id, command)
            await self._record(actor, "PRODUCT_IMAGE_CREATED", None, entity)
            return entity

    async def update_image(
        self,
        principal: Principal,
        product_id: UUID,
        image_id: UUID,
        changes: CatalogChanges,
    ) -> ProductImage:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            before = await self._repository.get_image(product_id, image_id)
            if before is None:
                raise CatalogNotFoundError("PRODUCT_IMAGE")
            self._changes(
                before, changes, {"url", "alt_text", "sort_order", "is_primary"}
            )
            entity = await self._repository.update_image(before, changes)
            await self._record(actor, "PRODUCT_IMAGE_UPDATED", before, entity)
            return entity

    async def archive_image(
        self, principal: Principal, product_id: UUID, image_id: UUID
    ) -> None:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            before = await self._repository.get_image(product_id, image_id)
            if before is None:
                raise CatalogNotFoundError("PRODUCT_IMAGE")
            entity = await self._repository.archive_image(before)
            await self._record(actor, "PRODUCT_IMAGE_ARCHIVED", before, entity)

    async def create_presentation(
        self, principal: Principal, product_id: UUID, command: PresentationCreate
    ) -> ProductPresentation:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            ProductPresentation(product_id=product_id, **asdict(command))
            entity = await self._repository.create_presentation(product_id, command)
            await self._record(actor, "PRODUCT_PRESENTATION_CREATED", None, entity)
            return entity

    async def update_presentation(
        self,
        principal: Principal,
        product_id: UUID,
        presentation_id: UUID,
        changes: CatalogChanges,
    ) -> ProductPresentation:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            before = await self._repository.get_presentation(
                product_id, presentation_id
            )
            if before is None:
                raise CatalogNotFoundError("PRESENTATION")
            self._changes(
                before,
                changes,
                {"name", "price_delta", "sort_order", "is_default", "is_active"},
            )
            entity = await self._repository.update_presentation(before, changes)
            await self._record(actor, "PRODUCT_PRESENTATION_UPDATED", before, entity)
            return entity

    async def archive_presentation(
        self, principal: Principal, product_id: UUID, presentation_id: UUID
    ) -> None:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            before = await self._repository.get_presentation(
                product_id, presentation_id
            )
            if before is None:
                raise CatalogNotFoundError("PRESENTATION")
            entity = await self._repository.archive_presentation(before)
            await self._record(actor, "PRODUCT_PRESENTATION_ARCHIVED", before, entity)

    async def create_addon(
        self, principal: Principal, product_id: UUID, command: AddonCreate
    ) -> ProductAddon:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            ProductAddon(product_id=product_id, **asdict(command))
            entity = await self._repository.create_addon(product_id, command)
            await self._record(actor, "PRODUCT_ADDON_CREATED", None, entity)
            return entity

    async def update_addon(
        self,
        principal: Principal,
        product_id: UUID,
        addon_id: UUID,
        changes: CatalogChanges,
    ) -> ProductAddon:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            before = await self._repository.get_addon(product_id, addon_id)
            if before is None:
                raise CatalogNotFoundError("ADDON")
            self._changes(
                before,
                changes,
                {
                    "name",
                    "is_required",
                    "min_select",
                    "max_select",
                    "sort_order",
                    "is_active",
                },
            )
            entity = await self._repository.update_addon(before, changes)
            await self._record(actor, "PRODUCT_ADDON_UPDATED", before, entity)
            return entity

    async def archive_addon(
        self, principal: Principal, product_id: UUID, addon_id: UUID
    ) -> None:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            before = await self._repository.get_addon(product_id, addon_id)
            if before is None:
                raise CatalogNotFoundError("ADDON")
            entity = await self._repository.archive_addon(before)
            await self._record(actor, "PRODUCT_ADDON_ARCHIVED", before, entity)

    async def _addon(self, product_id: UUID, addon_id: UUID) -> ProductAddon:
        addon = await self._repository.get_addon(product_id, addon_id)
        if addon is None:
            raise CatalogNotFoundError("ADDON")
        return addon

    async def create_option(
        self,
        principal: Principal,
        product_id: UUID,
        addon_id: UUID,
        command: OptionCreate,
    ) -> ProductAddonOption:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            await self._addon(product_id, addon_id)
            ProductAddonOption(product_addon_id=addon_id, **asdict(command))
            entity = await self._repository.create_option(addon_id, command)
            await self._record(actor, "PRODUCT_ADDON_OPTION_CREATED", None, entity)
            return entity

    async def update_option(
        self,
        principal: Principal,
        product_id: UUID,
        addon_id: UUID,
        option_id: UUID,
        changes: CatalogChanges,
    ) -> ProductAddonOption:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            await self._addon(product_id, addon_id)
            before = await self._repository.get_option(addon_id, option_id)
            if before is None:
                raise CatalogNotFoundError("ADDON_OPTION")
            self._changes(
                before, changes, {"name", "additional_price", "sort_order", "is_active"}
            )
            entity = await self._repository.update_option(before, changes)
            await self._record(actor, "PRODUCT_ADDON_OPTION_UPDATED", before, entity)
            return entity

    async def archive_option(
        self, principal: Principal, product_id: UUID, addon_id: UUID, option_id: UUID
    ) -> None:
        async with self._write(principal) as actor:
            await self._product(product_id, lock=True)
            await self._addon(product_id, addon_id)
            before = await self._repository.get_option(addon_id, option_id)
            if before is None:
                raise CatalogNotFoundError("ADDON_OPTION")
            entity = await self._repository.archive_option(before)
            await self._record(actor, "PRODUCT_ADDON_OPTION_ARCHIVED", before, entity)

    async def get_branch_product(
        self, principal: Principal, branch_id: UUID, product_id: UUID
    ) -> BranchProductConfig:
        await self.require_manage(principal, branch_id)
        await self._product(product_id)
        override = await self._repository.get_branch_product(branch_id, product_id)
        return BranchProductConfig(
            is_available=override.is_available if override else True,
            price_override=override.price_override if override else None,
        )

    async def upsert_branch_product(
        self,
        principal: Principal,
        branch_id: UUID,
        product_id: UUID,
        command: BranchProductConfig,
    ) -> BranchProduct:
        async with self._write(principal, branch_id) as actor:
            await self._product(product_id, lock=True)
            if command.price_override is not None:
                money(command.price_override)
            before = await self._repository.get_branch_product(branch_id, product_id)
            entity = await self._repository.upsert_branch_product(
                branch_id, product_id, command
            )
            await self._record(
                actor, "BRANCH_PRODUCT_UPDATED", before, entity, branch_id
            )
            return entity
