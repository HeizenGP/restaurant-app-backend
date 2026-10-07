from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import UUID, uuid4

from app.modules.auth.domain.models import Principal
from app.modules.cart.application.dtos import (
    AddonSelection,
    CartView,
    ItemCreate,
    ItemUpdate,
    ValidatedSelection,
)
from app.modules.cart.application.errors import (
    ActiveCartExistsError,
    CartBranchInvalidError,
    CartItemNotFoundError,
    CartNotFoundError,
    CartProductUnavailableError,
    CartRecalculationFailedError,
    CartSelectionInvalidError,
    InvalidCartDataError,
)
from app.modules.cart.application.ports import CartRepository, CatalogSelectionGateway
from app.modules.cart.domain.models import (
    Cart,
    CartItem,
    CartRuleError,
    SelectedOption,
    normalize_notes,
    validate_quantity,
)
from app.shared.application.exceptions import UnauthorizedError


def customer_identity(principal: Principal) -> UUID:
    if principal.customer_id is None:
        raise UnauthorizedError("Customer identity is required")
    return principal.customer_id


def item_addons(item: CartItem) -> tuple[AddonSelection, ...]:
    groups: dict[UUID, list[UUID]] = defaultdict(list)
    for option in item.selected_options:
        groups[option.product_addon_id].append(option.product_addon_option_id)
    return tuple(
        AddonSelection(addon_id, tuple(sorted(ids, key=str)))
        for addon_id, ids in sorted(groups.items(), key=lambda pair: str(pair[0]))
    )


class CartService:
    def __init__(
        self, repository: CartRepository, catalog: CatalogSelectionGateway
    ) -> None:
        self._repository = repository
        self._catalog = catalog

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[None]:
        try:
            yield
            await self._repository.commit()
        except CartRuleError:
            await self._repository.rollback()
            raise InvalidCartDataError() from None
        except Exception:
            await self._repository.rollback()
            raise

    async def _active(self, customer_id: UUID, *, lock: bool = False) -> Cart:
        cart = await self._repository.find_active(customer_id, lock=lock)
        if cart is None:
            raise CartNotFoundError()
        return cart

    async def _item(self, cart: Cart, item_id: UUID) -> CartItem:
        item = await self._repository.get_item(cart, item_id, lock=True)
        if item is None:
            raise CartItemNotFoundError()
        return item

    async def get_cart(self, principal: Principal) -> CartView:
        state = await self._repository.read_active(customer_identity(principal))
        if state is None:
            raise CartNotFoundError()
        return CartView.from_cart(*state)

    async def create_cart(self, principal: Principal, branch_id: UUID) -> CartView:
        customer_id = customer_identity(principal)
        async with self._write():
            if not await self._catalog.branch_is_active(branch_id):
                raise CartBranchInvalidError()
            if await self._repository.find_active(customer_id) is not None:
                raise ActiveCartExistsError()
            cart = await self._repository.create_cart(
                Cart(customer_id=customer_id, branch_id=branch_id)
            )
            return CartView.from_cart(cart, ())

    async def abandon_cart(self, principal: Principal) -> None:
        async with self._write():
            cart = await self._active(customer_identity(principal), lock=True)
            await self._repository.abandon_cart(cart)

    async def _selection(self, cart: Cart, command: ItemCreate) -> ValidatedSelection:
        validate_quantity(command.quantity)
        return await self._catalog.validate_selection(
            cart.branch_id,
            command.product_id,
            command.presentation_id,
            command.addons,
            normalize_notes(command.notes),
        )

    @staticmethod
    def _snapshot(
        cart: Cart,
        command: ItemCreate,
        validated: ValidatedSelection,
        previous: CartItem | None = None,
    ) -> CartItem:
        if (validated.branch_id, validated.product_id, validated.presentation_id) != (
            cart.branch_id,
            command.product_id,
            command.presentation_id,
        ):
            raise CartSelectionInvalidError()
        item_id = previous.id if previous else uuid4()
        old_options = {
            option.product_addon_option_id: option
            for option in (previous.selected_options if previous else ())
        }
        options = []
        for option in validated.options:
            old = old_options.get(option.option_id)
            fields = {"id": old.id, "created_at": old.created_at} if old else {}
            options.append(
                SelectedOption(
                    cart_item_id=item_id,
                    product_addon_id=option.addon_id,
                    product_addon_option_id=option.option_id,
                    additional_price_snapshot=option.additional_price,
                    **fields,
                )
            )
        values = dict(
            cart_id=cart.id,
            product_id=command.product_id,
            presentation_id=command.presentation_id,
            quantity=command.quantity,
            notes=normalize_notes(command.notes),
            base_price_snapshot=validated.base_price,
            presentation_price_snapshot=validated.presentation_price,
            addons_price_snapshot=validated.addons_price,
            unit_price_snapshot=validated.unit_price,
            selected_options=tuple(options),
        )
        return (
            replace(previous, **values) if previous else CartItem(id=item_id, **values)
        )

    async def add_item(self, principal: Principal, command: ItemCreate) -> CartItem:
        async with self._write():
            cart = await self._active(customer_identity(principal), lock=True)
            validated = await self._selection(cart, command)
            item = await self._repository.add_item(
                cart, self._snapshot(cart, command, validated)
            )
            await self._repository.touch_cart(cart)
            return item

    async def update_item(
        self, principal: Principal, item_id: UUID, update: ItemUpdate
    ) -> CartItem:
        async with self._write():
            if not update.provided_fields or not update.provided_fields <= {
                "quantity",
                "notes",
                "presentation_id",
                "addons",
            }:
                raise InvalidCartDataError()
            cart = await self._active(customer_identity(principal), lock=True)
            previous = await self._item(cart, item_id)
            provided = update.provided_fields
            if any(getattr(update, key) is None for key in provided - {"notes"}):
                raise InvalidCartDataError()
            command = ItemCreate(
                product_id=previous.product_id,
                presentation_id=update.presentation_id
                if "presentation_id" in provided
                else previous.presentation_id,
                quantity=update.quantity
                if "quantity" in provided
                else previous.quantity,
                notes=update.notes if "notes" in provided else previous.notes,
                addons=update.addons if "addons" in provided else item_addons(previous),
            )
            validated = await self._selection(cart, command)
            item = await self._repository.update_item(
                cart, self._snapshot(cart, command, validated, previous)
            )
            await self._repository.touch_cart(cart)
            return item

    async def delete_item(self, principal: Principal, item_id: UUID) -> None:
        async with self._write():
            cart = await self._active(customer_identity(principal), lock=True)
            await self._item(cart, item_id)
            await self._repository.delete_item(cart, item_id)
            await self._repository.touch_cart(cart)

    async def recalculate_cart(self, principal: Principal) -> CartView:
        async with self._write():
            cart = await self._active(customer_identity(principal), lock=True)
            items = await self._repository.list_items(cart)
            candidates = []
            try:
                # Validate all lines first. No partial repricing is ever committed.
                for item in items:
                    command = ItemCreate(
                        product_id=item.product_id,
                        presentation_id=item.presentation_id,
                        quantity=item.quantity,
                        notes=item.notes,
                        addons=item_addons(item),
                    )
                    validated = await self._selection(cart, command)
                    candidates.append(self._snapshot(cart, command, validated, item))
            except (
                CartSelectionInvalidError,
                CartProductUnavailableError,
                CartBranchInvalidError,
            ):
                raise CartRecalculationFailedError() from None
            if not items and not await self._catalog.branch_is_active(cart.branch_id):
                raise CartRecalculationFailedError()
            updated = []
            for item in candidates:
                updated.append(await self._repository.update_item(cart, item))
            cart = await self._repository.touch_cart(cart)
            return CartView.from_cart(cart, tuple(updated))
