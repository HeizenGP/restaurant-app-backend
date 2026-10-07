from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.models import BranchModel
from app.modules.cart.application.services import item_addons
from app.modules.cart.domain.models import Cart, CartStatus
from app.modules.cart.infrastructure.persistence.models import CartItemModel, CartModel
from app.modules.cart.infrastructure.persistence.repositories import (
    SQLAlchemyCartRepository,
)
from app.modules.catalog.application.dtos import AddonSelection
from app.modules.catalog.application.errors import (
    CatalogNotFoundError,
    InvalidSelectionError,
    ProductNotAvailableError,
)
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.domain.models import CatalogRuleError
from app.modules.catalog.infrastructure.persistence.models import (
    CategoryModel,
    ProductModel,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.models import OrderAddonOption, OrderItem


class SQLAlchemyCartCheckoutGateway:
    def __init__(self, session: AsyncSession, catalog: CatalogService) -> None:
        self._session = session
        self._carts = SQLAlchemyCartRepository(session)
        self._catalog_repository = SQLAlchemyCatalogRepository(session)
        self._catalog = catalog

    async def get_and_lock_active_cart(self, customer_id: UUID) -> Cart | None:
        return await self._carts.find_active(customer_id, lock=True)

    async def has_checked_out_cart(self, customer_id: UUID) -> bool:
        return (
            await self._session.execute(
                select(CartModel.id)
                .where(
                    CartModel.customer_id == customer_id,
                    CartModel.status == CartStatus.CHECKED_OUT,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def validate_for_checkout(self, cart: Cart) -> tuple[OrderItem, ...]:
        # Parent Cart lock serializes recalculate/PATCH/delete/abandon. Child
        # locks are acquired in deterministic order, never through CartService.
        await self._session.execute(
            select(CartItemModel.id)
            .where(CartItemModel.cart_id == cart.id)
            .order_by(CartItemModel.id)
            .with_for_update()
        )
        items = await self._carts.list_items(cart)
        if not items:
            return ()
        branch = (
            await self._session.execute(
                select(BranchModel.id)
                .where(
                    BranchModel.id == cart.branch_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
                .with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if branch is None:
            raise OrderConflictError("ORDER_SELECTION_INVALID")
        product_ids = sorted({item.product_id for item in items}, key=str)
        category_ids = set(
            (
                await self._session.execute(
                    select(CategoryModel.id)
                    .where(
                        CategoryModel.id.in_(
                            select(ProductModel.category_id).where(
                                ProductModel.id.in_(product_ids)
                            )
                        )
                    )
                    .order_by(CategoryModel.id)
                    .with_for_update(read=True)
                )
            ).scalars()
        )
        products = list(
            (
                await self._session.execute(
                    select(ProductModel)
                    .where(ProductModel.id.in_(product_ids))
                    .order_by(ProductModel.id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        # A product moved categories between the lock queries: retry, without
        # acquiring a new category lock out of order or creating partial Orders.
        if len(products) != len(product_ids) or any(
            row.category_id not in category_ids for row in products
        ):
            raise OrderConflictError("ORDER_SELECTION_INVALID")
        # Five batched Catalog queries, rather than five queries per cart line.
        aggregates = await self._catalog_repository.public_products(
            cart.branch_id, product_ids=tuple(product_ids)
        )
        try:
            public = {
                aggregate.product.id: self._catalog._public(aggregate)
                for aggregate in aggregates
            }
        except CatalogRuleError:
            raise OrderConflictError("ORDER_SELECTION_INVALID") from None
        snapshots = []
        for item in items:
            product = public.get(item.product_id)
            if product is None:
                raise OrderConflictError("ORDER_SELECTION_INVALID")
            try:
                selection = self._catalog.validate_product_selection(
                    cart.branch_id,
                    product,
                    item.presentation_id,
                    tuple(
                        AddonSelection(group.addon_id, group.option_ids)
                        for group in item_addons(item)
                    ),
                    item.notes,
                )
            except (
                CatalogNotFoundError,
                InvalidSelectionError,
                ProductNotAvailableError,
                CatalogRuleError,
            ):
                raise OrderConflictError("ORDER_SELECTION_INVALID") from None
            snapshots.append(
                OrderItem(
                    product_id=selection.product_id,
                    presentation_id=selection.presentation_id,
                    product_name_snapshot=selection.product_name,
                    presentation_name_snapshot=selection.presentation_name,
                    quantity=item.quantity,
                    notes=item.notes,
                    base_price_snapshot=selection.base_price,
                    presentation_price_snapshot=selection.presentation_price,
                    addons_price_snapshot=selection.addons_price,
                    unit_price_snapshot=selection.unit_price,
                    line_total_snapshot=selection.unit_price * item.quantity,
                    addon_options=tuple(
                        OrderAddonOption(
                            product_addon_id=option.addon_id,
                            product_addon_option_id=option.option_id,
                            addon_name_snapshot=option.addon_name,
                            option_name_snapshot=option.option_name,
                            additional_price_snapshot=option.additional_price,
                        )
                        for option in selection.selected_options
                    ),
                )
            )
        return tuple(snapshots)

    async def mark_checked_out(self, cart: Cart) -> None:
        result = await self._session.execute(
            update(CartModel)
            .where(
                CartModel.id == cart.id,
                CartModel.customer_id == cart.customer_id,
                CartModel.status == CartStatus.ACTIVE,
            )
            .values(status=CartStatus.CHECKED_OUT)
            .returning(CartModel.id)
        )
        if result.scalar_one_or_none() is None:
            raise OrderConflictError("ORDER_ALREADY_CREATED")
