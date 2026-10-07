from copy import deepcopy
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cart.application.errors import (
    ActiveCartExistsError,
    CartItemNotFoundError,
)
from app.modules.cart.application.services import CartService
from app.modules.cart.domain.models import Cart, CartItem, CartStatus
from app.modules.cart.infrastructure.catalog import CatalogSelectionAdapter
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.domain.models import (
    Category,
    Product,
    ProductAddon,
    ProductAddonOption,
    ProductPresentation,
)
from app.shared.domain.time import utc_now
from tests.modules.catalog.fakes import (
    Grant,
    MemoryAuditRecorder,
    MemoryCatalogAuthorization,
    MemoryCatalogRepository,
    seed,
)


class MemoryCartRepository:
    def __init__(self) -> None:
        self.carts: dict[UUID, Cart] = {}
        self.items: dict[UUID, CartItem] = {}
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self.fail_update_at: int | None = None
        self.updates = 0
        self.calls: list[tuple[str, bool]] = []
        self._snapshot = deepcopy((self.carts, self.items))

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("Simulated cart commit failure")
        self.commits += 1
        self._snapshot = deepcopy((self.carts, self.items))

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.carts, self.items = deepcopy(self._snapshot)

    async def find_active(
        self, customer_id: UUID, *, lock: bool = False
    ) -> Cart | None:
        self.calls.append(("cart", lock))
        return next(
            (
                cart
                for cart in self.carts.values()
                if cart.customer_id == customer_id and cart.status == CartStatus.ACTIVE
            ),
            None,
        )

    async def read_active(
        self, customer_id: UUID
    ) -> tuple[Cart, tuple[CartItem, ...]] | None:
        cart = await self.find_active(customer_id)
        if cart is None:
            return None
        return cart, tuple(await self.list_items(cart))

    async def create_cart(self, cart: Cart) -> Cart:
        if await self.find_active(cart.customer_id) is not None:
            raise ActiveCartExistsError()
        self.carts[cart.id] = cart
        return cart

    def owned(self, cart: Cart) -> bool:
        current = self.carts.get(cart.id)
        return (
            current is not None
            and current.customer_id == cart.customer_id
            and current.status == CartStatus.ACTIVE
        )

    async def abandon_cart(self, cart: Cart) -> None:
        if self.owned(cart):
            self.carts[cart.id] = replace(
                cart, status=CartStatus.ABANDONED, updated_at=utc_now()
            )

    async def touch_cart(self, cart: Cart) -> Cart:
        current = replace(self.carts[cart.id], updated_at=utc_now())
        self.carts[cart.id] = current
        return current

    async def list_items(self, cart: Cart) -> list[CartItem]:
        return sorted(
            (
                item
                for item in self.items.values()
                if item.cart_id == cart.id and self.owned(cart)
            ),
            key=lambda item: (item.created_at, item.id),
        )

    async def get_item(
        self, cart: Cart, item_id: UUID, *, lock: bool = False
    ) -> CartItem | None:
        self.calls.append(("item", lock))
        item = self.items.get(item_id)
        return item if item and item.cart_id == cart.id and self.owned(cart) else None

    async def add_item(self, cart: Cart, item: CartItem) -> CartItem:
        assert self.owned(cart) and item.cart_id == cart.id
        self.items[item.id] = item
        return item

    async def update_item(self, cart: Cart, item: CartItem) -> CartItem:
        self.updates += 1
        if self.fail_update_at == self.updates:
            raise RuntimeError("Simulated cart update failure")
        if await self.get_item(cart, item.id) is None:
            raise CartItemNotFoundError()
        updated = replace(item, updated_at=utc_now())
        self.items[item.id] = updated
        return updated

    async def delete_item(self, cart: Cart, item_id: UUID) -> None:
        if await self.get_item(cart, item_id) is None:
            raise CartItemNotFoundError()
        del self.items[item_id]


@dataclass
class CartSetup:
    service: CartService
    repository: MemoryCartRepository
    catalog: CatalogService
    catalog_repository: MemoryCatalogRepository
    admin: Principal
    guest: Principal
    registered: Principal
    branch: UUID
    other_branch: UUID
    category: Category
    product: Product
    personal: ProductPresentation
    family: ProductPresentation
    addon: ProductAddon
    free: ProductAddonOption
    paid: ProductAddonOption


async def cart_setup() -> CartSetup:
    catalog_repository = MemoryCatalogRepository()
    branch, other_branch = uuid4(), uuid4()
    catalog_repository.branches.update({branch, other_branch})
    admin = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    authorization = MemoryCatalogAuthorization(catalog_repository)
    authorization.grants[admin.user_id] = [
        Grant(branch_id=branch),
        Grant(branch_id=other_branch),
    ]
    catalog = CatalogService(
        catalog_repository, authorization, MemoryAuditRecorder(catalog_repository)
    )
    entities = await seed(catalog, admin)
    repository = MemoryCartRepository()
    return CartSetup(
        CartService(repository, CatalogSelectionAdapter(catalog, catalog_repository)),
        repository,
        catalog,
        catalog_repository,
        admin,
        Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4()),
        Principal(
            principal_type=PrincipalType.REGISTERED,
            user_id=uuid4(),
            customer_id=uuid4(),
        ),
        branch,
        other_branch,
        *entities,
    )
