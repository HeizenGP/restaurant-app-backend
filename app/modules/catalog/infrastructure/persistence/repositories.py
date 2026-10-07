from collections import defaultdict
from dataclasses import asdict, fields
from typing import TypeVar
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.models import BranchModel
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
from app.modules.catalog.domain.models import (
    BranchProduct,
    Category,
    Product,
    ProductAddon,
    ProductAddonOption,
    ProductImage,
    ProductPresentation,
)
from app.modules.catalog.infrastructure.persistence.models import (
    BranchProductModel,
    CategoryModel,
    ProductAddonModel,
    ProductAddonOptionModel,
    ProductImageModel,
    ProductModel,
    ProductPresentationModel,
)
from app.shared.domain.time import utc_now

Entity = TypeVar(
    "Entity",
    Category,
    Product,
    ProductImage,
    ProductPresentation,
    ProductAddon,
    ProductAddonOption,
    BranchProduct,
)


def to_entity(model: object, entity: type[Entity]) -> Entity:
    return entity(
        **{field.name: getattr(model, field.name) for field in fields(entity)}
    )


class SQLAlchemyCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def branch_is_active(self, branch_id: UUID) -> bool:
        query = select(BranchModel.id).where(
            BranchModel.id == branch_id,
            BranchModel.is_active.is_(True),
            BranchModel.deleted_at.is_(None),
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None

    async def list_categories(self) -> list[Category]:
        result = await self._session.execute(
            select(CategoryModel)
            .where(
                CategoryModel.deleted_at.is_(None),
            )
            .order_by(CategoryModel.sort_order, CategoryModel.name, CategoryModel.id)
        )
        return [to_entity(row, Category) for row in result.scalars()]

    async def list_products(self) -> list[Product]:
        result = await self._session.execute(
            select(ProductModel)
            .where(
                ProductModel.deleted_at.is_(None),
            )
            .order_by(ProductModel.sort_order, ProductModel.name, ProductModel.id)
        )
        return [to_entity(row, Product) for row in result.scalars()]

    async def get_category(
        self, category_id: UUID, *, lock: bool = False
    ) -> Category | None:
        query = select(CategoryModel).where(
            CategoryModel.id == category_id,
            CategoryModel.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return None if row is None else to_entity(row, Category)

    async def get_product(
        self, product_id: UUID, *, lock: bool = False
    ) -> Product | None:
        query = select(ProductModel).where(
            ProductModel.id == product_id,
            ProductModel.deleted_at.is_(None),
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return None if row is None else to_entity(row, Product)

    async def category_has_active_products(self, category_id: UUID) -> bool:
        query = (
            select(ProductModel.id)
            .where(
                ProductModel.category_id == category_id,
                ProductModel.is_active.is_(True),
                ProductModel.deleted_at.is_(None),
            )
            .limit(1)
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None

    async def public_products(
        self, branch_id: UUID, product_id: UUID | None = None
    ) -> list[ProductAggregate]:
        selectable = exists(
            select(ProductPresentationModel.id).where(
                ProductPresentationModel.product_id == ProductModel.id,
                ProductPresentationModel.is_active.is_(True),
                ProductPresentationModel.deleted_at.is_(None),
            )
        )
        query = (
            select(ProductModel, CategoryModel, BranchProductModel)
            .join(CategoryModel, CategoryModel.id == ProductModel.category_id)
            .outerjoin(
                BranchProductModel,
                (BranchProductModel.product_id == ProductModel.id)
                & (BranchProductModel.branch_id == branch_id),
            )
            .where(
                ProductModel.is_active.is_(True),
                ProductModel.deleted_at.is_(None),
                CategoryModel.is_active.is_(True),
                CategoryModel.deleted_at.is_(None),
                selectable,
            )
            .order_by(
                CategoryModel.sort_order,
                CategoryModel.name,
                CategoryModel.id,
                ProductModel.sort_order,
                ProductModel.name,
                ProductModel.id,
            )
        )
        if product_id is not None:
            query = query.where(ProductModel.id == product_id)
        rows = (await self._session.execute(query)).all()
        return await self._aggregates(rows, public=True)

    async def admin_product(self, product_id: UUID) -> ProductAggregate | None:
        query = (
            select(ProductModel, CategoryModel)
            .join(
                CategoryModel,
                CategoryModel.id == ProductModel.category_id,
            )
            .where(ProductModel.id == product_id, ProductModel.deleted_at.is_(None))
        )
        row = (await self._session.execute(query)).one_or_none()
        if row is None:
            return None
        return (await self._aggregates([(row[0], row[1], None)], public=False))[0]

    async def _aggregates(
        self,
        rows: list[tuple[ProductModel, CategoryModel, BranchProductModel | None]],
        *,
        public: bool,
    ) -> list[ProductAggregate]:
        # Five bounded queries total, independent of the number of products.
        # Each child table is loaded in its own batch to avoid cross-products.
        if not rows:
            return []
        ids = [row[0].id for row in rows]
        images_query = (
            select(ProductImageModel)
            .where(
                ProductImageModel.product_id.in_(ids),
                ProductImageModel.deleted_at.is_(None),
            )
            .order_by(ProductImageModel.sort_order, ProductImageModel.id)
        )
        presentations_query = (
            select(ProductPresentationModel)
            .where(
                ProductPresentationModel.product_id.in_(ids),
                ProductPresentationModel.deleted_at.is_(None),
            )
            .order_by(
                ProductPresentationModel.sort_order,
                ProductPresentationModel.name,
                ProductPresentationModel.id,
            )
        )
        addons_query = (
            select(ProductAddonModel)
            .where(
                ProductAddonModel.product_id.in_(ids),
                ProductAddonModel.deleted_at.is_(None),
            )
            .order_by(
                ProductAddonModel.sort_order,
                ProductAddonModel.name,
                ProductAddonModel.id,
            )
        )
        if public:
            presentations_query = presentations_query.where(
                ProductPresentationModel.is_active.is_(True)
            )
            addons_query = addons_query.where(ProductAddonModel.is_active.is_(True))
        images = (await self._session.execute(images_query)).scalars().all()
        presentations = (
            (await self._session.execute(presentations_query)).scalars().all()
        )
        addons = (await self._session.execute(addons_query)).scalars().all()
        options = []
        if addons:
            options_query = (
                select(ProductAddonOptionModel)
                .where(
                    ProductAddonOptionModel.product_addon_id.in_(
                        [addon.id for addon in addons]
                    ),
                    ProductAddonOptionModel.deleted_at.is_(None),
                )
                .order_by(
                    ProductAddonOptionModel.sort_order,
                    ProductAddonOptionModel.name,
                    ProductAddonOptionModel.id,
                )
            )
            if public:
                options_query = options_query.where(
                    ProductAddonOptionModel.is_active.is_(True)
                )
            options = (await self._session.execute(options_query)).scalars().all()
        by_images: dict[UUID, list[ProductImage]] = defaultdict(list)
        by_presentations: dict[UUID, list[ProductPresentation]] = defaultdict(list)
        by_addons: dict[UUID, list[ProductAddon]] = defaultdict(list)
        by_options: dict[UUID, list[ProductAddonOption]] = defaultdict(list)
        addon_products = {addon.id: addon.product_id for addon in addons}
        for row in images:
            by_images[row.product_id].append(to_entity(row, ProductImage))
        for row in presentations:
            by_presentations[row.product_id].append(to_entity(row, ProductPresentation))
        for row in addons:
            by_addons[row.product_id].append(to_entity(row, ProductAddon))
        for row in options:
            by_options[addon_products[row.product_addon_id]].append(
                to_entity(row, ProductAddonOption)
            )
        return [
            ProductAggregate(
                product=to_entity(product, Product),
                category=to_entity(category, Category),
                override=None
                if override is None
                else BranchProductConfig(
                    is_available=override.is_available,
                    price_override=override.price_override,
                ),
                images=tuple(by_images[product.id]),
                presentations=tuple(by_presentations[product.id]),
                addons=tuple(by_addons[product.id]),
                options=tuple(by_options[product.id]),
            )
            for product, category, override in rows
        ]

    async def _persist(self, model: object, entity: type[Entity]) -> Entity:
        self._session.add(model)
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, entity)

    async def _patch(
        self, model: object, changes: CatalogChanges, entity: type[Entity]
    ) -> Entity:
        for name, value in changes.values.items():
            setattr(model, name, value)
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, entity)

    async def create_category(self, command: CategoryCreate) -> Category:
        return await self._persist(CategoryModel(**asdict(command)), Category)

    async def update_category(
        self, category: Category, changes: CatalogChanges
    ) -> Category:
        model = await self._session.get(CategoryModel, category.id)
        return await self._patch(model, changes, Category)

    async def archive_category(self, category: Category) -> Category:
        model = await self._session.get(CategoryModel, category.id)
        model.deleted_at = utc_now()
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, Category)

    async def create_product(self, command: ProductCreate) -> Product:
        return await self._persist(ProductModel(**asdict(command)), Product)

    async def update_product(
        self, product: Product, changes: CatalogChanges
    ) -> Product:
        model = await self._session.get(ProductModel, product.id)
        return await self._patch(model, changes, Product)

    async def archive_product(self, product: Product) -> Product:
        model = await self._session.get(ProductModel, product.id)
        model.deleted_at = utc_now()
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, Product)

    async def get_image(self, product_id: UUID, image_id: UUID) -> ProductImage | None:
        row = (
            await self._session.execute(
                select(ProductImageModel).where(
                    ProductImageModel.id == image_id,
                    ProductImageModel.product_id == product_id,
                    ProductImageModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return None if row is None else to_entity(row, ProductImage)

    async def create_image(
        self, product_id: UUID, command: ImageCreate
    ) -> ProductImage:
        if command.is_primary:
            await self._clear_primary(product_id)
        return await self._persist(
            ProductImageModel(product_id=product_id, **asdict(command)), ProductImage
        )

    async def update_image(
        self, image: ProductImage, changes: CatalogChanges
    ) -> ProductImage:
        if changes.values.get("is_primary", image.is_primary):
            await self._clear_primary(image.product_id, excluding=image.id)
        model = await self._session.get(ProductImageModel, image.id)
        return await self._patch(model, changes, ProductImage)

    async def archive_image(self, image: ProductImage) -> ProductImage:
        model = await self._session.get(ProductImageModel, image.id)
        model.deleted_at = utc_now()
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, ProductImage)

    async def get_presentation(
        self, product_id: UUID, presentation_id: UUID
    ) -> ProductPresentation | None:
        row = (
            await self._session.execute(
                select(ProductPresentationModel).where(
                    ProductPresentationModel.id == presentation_id,
                    ProductPresentationModel.product_id == product_id,
                    ProductPresentationModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return None if row is None else to_entity(row, ProductPresentation)

    async def create_presentation(
        self, product_id: UUID, command: PresentationCreate
    ) -> ProductPresentation:
        if command.is_default and command.is_active:
            await self._clear_default(product_id)
        return await self._persist(
            ProductPresentationModel(product_id=product_id, **asdict(command)),
            ProductPresentation,
        )

    async def update_presentation(
        self, presentation: ProductPresentation, changes: CatalogChanges
    ) -> ProductPresentation:
        if changes.values.get(
            "is_default", presentation.is_default
        ) and changes.values.get("is_active", presentation.is_active):
            await self._clear_default(
                presentation.product_id, excluding=presentation.id
            )
        model = await self._session.get(ProductPresentationModel, presentation.id)
        return await self._patch(model, changes, ProductPresentation)

    async def archive_presentation(
        self, presentation: ProductPresentation
    ) -> ProductPresentation:
        model = await self._session.get(ProductPresentationModel, presentation.id)
        model.deleted_at = utc_now()
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, ProductPresentation)

    async def get_addon(self, product_id: UUID, addon_id: UUID) -> ProductAddon | None:
        row = (
            await self._session.execute(
                select(ProductAddonModel).where(
                    ProductAddonModel.id == addon_id,
                    ProductAddonModel.product_id == product_id,
                    ProductAddonModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return None if row is None else to_entity(row, ProductAddon)

    async def create_addon(
        self, product_id: UUID, command: AddonCreate
    ) -> ProductAddon:
        return await self._persist(
            ProductAddonModel(product_id=product_id, **asdict(command)), ProductAddon
        )

    async def update_addon(
        self, addon: ProductAddon, changes: CatalogChanges
    ) -> ProductAddon:
        model = await self._session.get(ProductAddonModel, addon.id)
        return await self._patch(model, changes, ProductAddon)

    async def archive_addon(self, addon: ProductAddon) -> ProductAddon:
        model = await self._session.get(ProductAddonModel, addon.id)
        model.deleted_at = utc_now()
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, ProductAddon)

    async def get_option(
        self, addon_id: UUID, option_id: UUID
    ) -> ProductAddonOption | None:
        row = (
            await self._session.execute(
                select(ProductAddonOptionModel).where(
                    ProductAddonOptionModel.id == option_id,
                    ProductAddonOptionModel.product_addon_id == addon_id,
                    ProductAddonOptionModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return None if row is None else to_entity(row, ProductAddonOption)

    async def create_option(
        self, addon_id: UUID, command: OptionCreate
    ) -> ProductAddonOption:
        return await self._persist(
            ProductAddonOptionModel(product_addon_id=addon_id, **asdict(command)),
            ProductAddonOption,
        )

    async def update_option(
        self, option: ProductAddonOption, changes: CatalogChanges
    ) -> ProductAddonOption:
        model = await self._session.get(ProductAddonOptionModel, option.id)
        return await self._patch(model, changes, ProductAddonOption)

    async def archive_option(self, option: ProductAddonOption) -> ProductAddonOption:
        model = await self._session.get(ProductAddonOptionModel, option.id)
        model.deleted_at = utc_now()
        await self._flush()
        await self._session.refresh(model)
        return to_entity(model, ProductAddonOption)

    async def _clear_primary(
        self, product_id: UUID, *, excluding: UUID | None = None
    ) -> None:
        await self._session.execute(
            update(ProductImageModel)
            .where(
                ProductImageModel.product_id == product_id,
                ProductImageModel.deleted_at.is_(None),
                ProductImageModel.is_primary.is_(True),
                ProductImageModel.id != excluding,
            )
            .values(is_primary=False)
        )

    async def _clear_default(
        self, product_id: UUID, *, excluding: UUID | None = None
    ) -> None:
        await self._session.execute(
            update(ProductPresentationModel)
            .where(
                ProductPresentationModel.product_id == product_id,
                ProductPresentationModel.deleted_at.is_(None),
                ProductPresentationModel.is_active.is_(True),
                ProductPresentationModel.is_default.is_(True),
                ProductPresentationModel.id != excluding,
            )
            .values(is_default=False)
        )

    async def get_branch_product(
        self, branch_id: UUID, product_id: UUID
    ) -> BranchProduct | None:
        query = select(BranchProductModel).where(
            BranchProductModel.branch_id == branch_id,
            BranchProductModel.product_id == product_id,
        )
        row = (await self._session.execute(query)).scalar_one_or_none()
        return None if row is None else to_entity(row, BranchProduct)

    async def upsert_branch_product(
        self, branch_id: UUID, product_id: UUID, command: BranchProductConfig
    ) -> BranchProduct:
        query = insert(BranchProductModel).values(
            branch_id=branch_id,
            product_id=product_id,
            is_available=command.is_available,
            price_override=command.price_override,
        )
        query = (
            query.on_conflict_do_update(
                constraint="uq_branch_products_branch_id_product_id",
                set_={
                    "is_available": query.excluded.is_available,
                    "price_override": query.excluded.price_override,
                },
            )
            .returning(BranchProductModel)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(query)).scalar_one()
        return to_entity(row, BranchProduct)

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            raise self._integrity_error(exc) from None

    async def rollback(self) -> None:
        await self._session.rollback()

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise self._integrity_error(exc) from None

    @staticmethod
    def _integrity_error(exc: IntegrityError) -> CatalogConflictError:
        original = exc.orig
        constraint = getattr(original, "constraint_name", None) or getattr(
            getattr(original, "__cause__", None), "constraint_name", None
        )
        codes = {
            "uq_categories_slug": "CATEGORY_SLUG_CONFLICT",
            "uq_categories_name": "CATEGORY_NAME_CONFLICT",
            "uq_products_slug": "PRODUCT_SLUG_CONFLICT",
        }
        return CatalogConflictError(codes.get(constraint, "CATALOG_CONFLICT"))
