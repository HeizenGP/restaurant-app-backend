from collections import defaultdict
from dataclasses import fields
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.modules.cart.application.errors import (
    ActiveCartExistsError,
    CartConflictError,
    CartItemNotFoundError,
)
from app.modules.cart.domain.models import Cart, CartItem, CartStatus, SelectedOption
from app.modules.cart.infrastructure.persistence.models import (
    CartItemAddonOptionModel,
    CartItemModel,
    CartModel,
)


def cart_entity(model: CartModel) -> Cart:
    return Cart(
        id=model.id,
        customer_id=model.customer_id,
        branch_id=model.branch_id,
        status=CartStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SQLAlchemyCartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read_active(
        self, customer_id: UUID
    ) -> tuple[Cart, tuple[CartItem, ...]] | None:
        # A single statement gives a consistent MVCC snapshot of all three tables.
        # GET never locks, writes, or consults Catalog, even during repricing.
        query = (
            select(CartModel, CartItemModel, CartItemAddonOptionModel)
            .select_from(CartModel)
            .outerjoin(CartItemModel, CartItemModel.cart_id == CartModel.id)
            .outerjoin(
                CartItemAddonOptionModel,
                CartItemAddonOptionModel.cart_item_id == CartItemModel.id,
            )
            .where(CartModel.customer_id == customer_id, CartModel.status == "ACTIVE")
            .execution_options(populate_existing=True)
            .order_by(
                CartItemModel.created_at,
                CartItemModel.id,
                CartItemAddonOptionModel.created_at,
                CartItemAddonOptionModel.id,
            )
        )
        rows = (await self._session.execute(query)).all()
        if not rows:
            return None
        items: dict[UUID, CartItemModel] = {}
        options: dict[UUID, list[SelectedOption]] = defaultdict(list)
        for _, item, option in rows:
            if item is not None:
                items[item.id] = item
                if option is not None:
                    options[item.id].append(
                        SelectedOption(
                            **{
                                field.name: getattr(option, field.name)
                                for field in fields(SelectedOption)
                            }
                        )
                    )
        return cart_entity(rows[0][0]), tuple(
            CartItem(
                **{
                    field.name: getattr(item, field.name)
                    for field in fields(CartItem)
                    if field.name != "selected_options"
                },
                selected_options=tuple(options[item.id]),
            )
            for item in items.values()
        )

    @staticmethod
    def _translate(exc: IntegrityError) -> None:
        diagnostic = getattr(exc.orig, "diag", None)
        constraint = getattr(diagnostic, "constraint_name", None)
        if constraint is None:
            constraint = getattr(exc.orig, "constraint_name", None)
        if constraint is None:
            constraint = getattr(
                getattr(exc.orig, "__cause__", None), "constraint_name", None
            )
        if constraint == "uq_carts_active_customer":
            raise ActiveCartExistsError() from None
        raise CartConflictError() from None

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            self._translate(exc)

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            self._translate(exc)

    async def rollback(self) -> None:
        await self._session.rollback()

    async def find_active(
        self, customer_id: UUID, *, lock: bool = False
    ) -> Cart | None:
        query = select(CartModel).where(
            CartModel.customer_id == customer_id, CartModel.status == "ACTIVE"
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return None if row is None else cart_entity(row)

    async def create_cart(self, cart: Cart) -> Cart:
        row = CartModel(
            id=cart.id, customer_id=cart.customer_id, branch_id=cart.branch_id
        )
        self._session.add(row)
        await self._flush()
        await self._session.refresh(row)
        return cart_entity(row)

    @staticmethod
    def _cart_scope(cart: Cart) -> tuple[ColumnElement[bool], ...]:
        return (
            CartModel.id == cart.id,
            CartModel.customer_id == cart.customer_id,
            CartModel.status == "ACTIVE",
        )

    async def abandon_cart(self, cart: Cart) -> None:
        await self._session.execute(
            update(CartModel).where(*self._cart_scope(cart)).values(status="ABANDONED")
        )
        await self._flush()

    async def touch_cart(self, cart: Cart) -> Cart:
        # Force a parent UPDATE; the existing DB trigger owns updated_at.
        await self._session.execute(
            update(CartModel)
            .where(*self._cart_scope(cart))
            .values(status=CartModel.status)
        )
        row = await self._session.get(CartModel, cart.id)
        await self._session.refresh(row)
        return cart_entity(row)

    def _items_query(self, cart: Cart) -> Select[tuple[CartItemModel]]:
        return (
            select(CartItemModel)
            .join(CartModel, CartModel.id == CartItemModel.cart_id)
            .where(*self._cart_scope(cart))
            .execution_options(populate_existing=True)
        )

    async def list_items(self, cart: Cart) -> list[CartItem]:
        rows = (
            (
                await self._session.execute(
                    self._items_query(cart).order_by(
                        CartItemModel.created_at, CartItemModel.id
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self._with_options(list(rows))

    async def get_item(
        self, cart: Cart, item_id: UUID, *, lock: bool = False
    ) -> CartItem | None:
        query = self._items_query(cart).where(CartItemModel.id == item_id)
        if lock:
            query = query.with_for_update(of=CartItemModel).execution_options(
                populate_existing=True
            )
        row = (await self._session.execute(query)).scalar_one_or_none()
        return None if row is None else (await self._with_options([row]))[0]

    async def _with_options(self, rows: list[CartItemModel]) -> list[CartItem]:
        if not rows:
            return []
        result = await self._session.execute(
            select(CartItemAddonOptionModel)
            .where(CartItemAddonOptionModel.cart_item_id.in_([row.id for row in rows]))
            .order_by(CartItemAddonOptionModel.created_at, CartItemAddonOptionModel.id)
        )
        grouped: dict[UUID, list[SelectedOption]] = defaultdict(list)
        for row in result.scalars():
            grouped[row.cart_item_id].append(
                SelectedOption(
                    **{
                        field.name: getattr(row, field.name)
                        for field in fields(SelectedOption)
                    }
                )
            )
        return [
            CartItem(
                **{
                    field.name: getattr(row, field.name)
                    for field in fields(CartItem)
                    if field.name != "selected_options"
                },
                selected_options=tuple(grouped[row.id]),
            )
            for row in rows
        ]

    async def _replace_options(self, item: CartItem) -> None:
        await self._session.execute(
            delete(CartItemAddonOptionModel).where(
                CartItemAddonOptionModel.cart_item_id == item.id
            )
        )
        self._session.add_all(
            [
                CartItemAddonOptionModel(
                    **{
                        field.name: getattr(option, field.name)
                        for field in fields(SelectedOption)
                    }
                )
                for option in item.selected_options
            ]
        )
        await self._flush()

    async def add_item(self, cart: Cart, item: CartItem) -> CartItem:
        if item.cart_id != cart.id:
            raise CartItemNotFoundError()
        row = CartItemModel(
            **{
                field.name: getattr(item, field.name)
                for field in fields(CartItem)
                if field.name != "selected_options"
            }
        )
        self._session.add(row)
        await self._flush()
        await self._replace_options(item)
        await self._session.refresh(row)
        return (await self._with_options([row]))[0]

    async def update_item(self, cart: Cart, item: CartItem) -> CartItem:
        row = (
            await self._session.execute(
                self._items_query(cart).where(CartItemModel.id == item.id)
            )
        ).scalar_one_or_none()
        if row is None or item.cart_id != cart.id:
            raise CartItemNotFoundError()
        for name in (
            "presentation_id",
            "quantity",
            "notes",
            "base_price_snapshot",
            "presentation_price_snapshot",
            "addons_price_snapshot",
            "unit_price_snapshot",
        ):
            setattr(row, name, getattr(item, name))
        # Even unchanged repricing is an explicit validated mutation.
        await self._session.execute(
            update(CartItemModel)
            .where(CartItemModel.id == item.id, CartItemModel.cart_id == cart.id)
            .values(quantity=item.quantity)
        )
        await self._flush()
        await self._replace_options(item)
        await self._session.refresh(row)
        return (await self._with_options([row]))[0]

    async def delete_item(self, cart: Cart, item_id: UUID) -> None:
        ownership = exists(select(CartModel.id).where(*self._cart_scope(cart)))
        await self._session.execute(
            delete(CartItemModel).where(
                CartItemModel.id == item_id, CartItemModel.cart_id == cart.id, ownership
            )
        )
        await self._flush()
