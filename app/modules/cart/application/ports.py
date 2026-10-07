from typing import Protocol
from uuid import UUID

from app.modules.cart.application.dtos import AddonSelection, ValidatedSelection
from app.modules.cart.domain.models import Cart, CartItem


class CatalogSelectionGateway(Protocol):
    async def branch_is_active(self, branch_id: UUID) -> bool: ...

    async def validate_selection(
        self,
        branch_id: UUID,
        product_id: UUID,
        presentation_id: UUID,
        addons: tuple[AddonSelection, ...],
        notes: str | None,
    ) -> ValidatedSelection: ...


class CartRepository(Protocol):
    async def read_active(
        self, customer_id: UUID
    ) -> tuple[Cart, tuple[CartItem, ...]] | None: ...

    async def find_active(
        self, customer_id: UUID, *, lock: bool = False
    ) -> Cart | None: ...

    async def create_cart(self, cart: Cart) -> Cart: ...

    async def abandon_cart(self, cart: Cart) -> None: ...

    async def touch_cart(self, cart: Cart) -> Cart: ...

    async def list_items(self, cart: Cart) -> list[CartItem]: ...

    async def get_item(
        self, cart: Cart, item_id: UUID, *, lock: bool = False
    ) -> CartItem | None: ...

    async def add_item(self, cart: Cart, item: CartItem) -> CartItem: ...

    async def update_item(self, cart: Cart, item: CartItem) -> CartItem: ...

    async def delete_item(self, cart: Cart, item_id: UUID) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
