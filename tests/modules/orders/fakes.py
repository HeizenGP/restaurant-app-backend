import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.modules.cart.application.dtos import (
    AddonSelection as CartAddonSelection,
)
from app.modules.cart.application.dtos import (
    ItemCreate,
)
from app.modules.cart.application.services import item_addons
from app.modules.cart.domain.models import CartStatus
from app.modules.catalog.application.dtos import AddonSelection
from app.modules.catalog.application.errors import (
    CatalogNotFoundError,
    InvalidSelectionError,
    ProductNotAvailableError,
)
from app.modules.orders.application.dtos import (
    AddressSnapshot,
    BranchHours,
    CustomerSnapshot,
    OrderCreate,
    PreparationEstimate,
)
from app.modules.orders.application.errors import (
    OrderConflictError,
    OrderUniqueConflictError,
)
from app.modules.orders.application.services import OrderService, OrderSettingsService
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    DeliveryZone,
    OrderAddonOption,
    OrderItem,
    OrderMode,
    OrderStatus,
    RestaurantTable,
)
from app.modules.orders.domain.transitions import QUEUE_STATUSES
from tests.modules.cart.fakes import CartSetup, cart_setup


class Store:
    def __init__(self, cart: CartSetup) -> None:
        self.cart = cart
        self.orders = {}
        self.settings = {}
        self.tables = {}
        self.zones = {}
        self.customers = {}
        self.addresses = {}
        self.hours = {}
        self.grants = set()
        self.lock = asyncio.Lock()
        self.sequence = 0
        self.commits = 0
        self.rollbacks = 0

    def snapshot(self):
        return deepcopy(
            (
                self.orders,
                self.settings,
                self.tables,
                self.zones,
                self.cart.repository.carts,
                self.cart.repository.items,
            )
        )

    def restore(self, state):
        (
            self.orders,
            self.settings,
            self.tables,
            self.zones,
            self.cart.repository.carts,
            self.cart.repository.items,
        ) = deepcopy(state)


class MemoryOrderSession:
    """Separate transaction per concurrent test request, sharing persisted state."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.before = None
        self.locked = False
        self.fail_item = None
        self.fail_commit = False
        self.fail_checkout = False
        self.calls = []

    async def begin(self):
        if not self.locked:
            await self.store.lock.acquire()
            self.locked = True
            self.before = self.store.snapshot()

    def close(self):
        if self.locked:
            self.store.lock.release()
            self.locked = False

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("Simulated final commit failure")
        self.store.commits += 1
        await self.store.cart.repository.commit()
        self.close()

    async def rollback(self):
        self.store.rollbacks += 1
        if self.locked and self.before is not None:
            self.store.restore(self.before)
        self.close()

    async def by_idempotency(self, customer_id, key):
        return next(
            (
                order
                for order in self.store.orders.values()
                if order.customer_id == customer_id and order.idempotency_key == key
            ),
            None,
        )

    async def get_owned(self, customer_id, order_id):
        order = self.store.orders.get(order_id)
        return order if order and order.customer_id == customer_id else None

    async def list_owned(self, customer_id, limit, offset):
        orders = sorted(
            (
                order
                for order in self.store.orders.values()
                if order.customer_id == customer_id
            ),
            key=lambda order: (order.created_at, order.id),
            reverse=True,
        )
        return orders[offset : offset + limit]

    async def create(self, order):
        if any(
            existing.source_cart_id == order.source_cart_id
            for existing in self.store.orders.values()
        ):
            raise OrderUniqueConflictError("uq_orders_source_cart")
        self.store.sequence += 1
        order = replace(order, order_number=self.store.sequence)
        self.store.orders[order.id] = order
        for index, _item in enumerate(order.items, start=1):
            self.calls.append(("insert_item", index))
            if index == self.fail_item:
                raise RuntimeError("Simulated item insert failure")
        return order

    async def lock_order(self, order_id):
        await self.begin()
        return self.store.orders.get(order_id)

    async def release_cash(self, order, history):
        updated = replace(
            order,
            status=OrderStatus.WAITING,
            confirmed_at=history.created_at,
            updated_at=history.created_at,
            history=(*order.history, history),
        )
        self.store.orders[order.id] = updated
        return updated

    async def lock_customer(self, customer_id):
        await self.begin()
        return self.store.customers.get(customer_id)

    async def address(self, customer_id, address_id):
        entry = self.store.addresses.get(address_id)
        return entry[1] if entry and entry[0] == customer_id else None

    async def get_and_lock_active_cart(self, customer_id):
        self.calls.append(("lock_cart", True))
        return await self.store.cart.repository.find_active(customer_id, lock=True)

    async def has_checked_out_cart(self, customer_id):
        return any(
            cart.customer_id == customer_id and cart.status == CartStatus.CHECKED_OUT
            for cart in self.store.cart.repository.carts.values()
        )

    async def validate_for_checkout(self, cart):
        if cart.branch_id not in self.store.cart.catalog_repository.branches:
            raise OrderConflictError("ORDER_SELECTION_INVALID")
        items = await self.store.cart.repository.list_items(cart)
        result = []
        for item in items:
            try:
                selection = await self.store.cart.catalog.validate_selection(
                    cart.branch_id,
                    item.product_id,
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
            ):
                raise OrderConflictError("ORDER_SELECTION_INVALID") from None
            result.append(
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
        return tuple(result)

    async def mark_checked_out(self, cart):
        self.store.cart.repository.carts[cart.id] = replace(
            cart, status=CartStatus.CHECKED_OUT
        )
        if self.fail_checkout:
            raise RuntimeError("Simulated checkout update failure")

    async def branch_is_active(self, branch_id):
        return branch_id in self.store.cart.catalog_repository.branches

    async def get_settings(self, branch_id, *, lock=False, for_update=False):
        if for_update:
            await self.begin()
        return self.store.settings.get(
            branch_id, BranchOrderSettings(branch_id=branch_id)
        )

    async def save_settings(self, settings):
        await self.begin()
        self.store.settings[settings.branch_id] = settings
        return settings

    async def branch_hours(self, branch_id):
        return BranchHours(self.store.hours.get(branch_id, ()))

    async def table_by_qr(self, qr_token):
        return next(
            (
                table
                for table in self.store.tables.values()
                if table.qr_token == qr_token
            ),
            None,
        )

    async def list_tables(self, branch_id):
        return [
            table
            for table in self.store.tables.values()
            if table.branch_id == branch_id
        ]

    async def get_table(self, branch_id, table_id):
        await self.begin()
        table = self.store.tables.get(table_id)
        return table if table and table.branch_id == branch_id else None

    async def save_table(self, table):
        await self.begin()
        self.store.tables[table.id] = table
        return table

    async def resolve_zone(self, branch_id, district):
        zones = [
            zone
            for zone in self.store.zones.values()
            if zone.is_active
            and zone.district.casefold() == district.strip().casefold()
            and zone.branch_id in (None, branch_id)
        ]
        return (
            min(
                zones,
                key=lambda zone: (
                    0
                    if zone.branch_id is None and zone.is_free
                    else 1
                    if zone.branch_id == branch_id
                    else 2
                ),
            )
            if zones
            else None
        )

    async def list_zones(self, branch_id):
        return [
            zone
            for zone in self.store.zones.values()
            if zone.branch_id in (None, branch_id)
        ]

    async def get_zone(self, branch_id, zone_id):
        await self.begin()
        zone = self.store.zones.get(zone_id)
        return zone if zone and zone.branch_id == branch_id else None

    async def save_zone(self, zone):
        await self.begin()
        if any(
            other.id != zone.id
            and other.branch_id == zone.branch_id
            and other.district.casefold() == zone.district.casefold()
            for other in self.store.zones.values()
        ):
            raise OrderConflictError()
        self.store.zones[zone.id] = zone
        return zone

    async def estimate(self, branch_id, settings):
        depth = sum(
            order.branch_id == branch_id and order.status in QUEUE_STATUSES
            for order in self.store.orders.values()
        )
        return PreparationEstimate(
            depth,
            settings.default_prep_minutes,
            depth * settings.queue_delay_per_order_minutes,
        )

    async def has_permission(self, user_id, branch_id, permission):
        return (user_id, branch_id, permission) in self.store.grants


@dataclass
class OrdersSetup:
    cart: CartSetup
    store: Store
    session: MemoryOrderSession
    service: OrderService
    admin_service: OrderSettingsService
    table: RestaurantTable
    address: AddressSnapshot
    now: datetime

    def local(self, method="CASH"):
        from app.modules.orders.domain.models import PaymentMethodType

        return OrderCreate(
            mode=OrderMode.LOCAL,
            table_qr_token=self.table.qr_token,
            payment_method=PaymentMethodType(method),
        )

    def delivery(self):
        return OrderCreate(mode=OrderMode.DELIVERY, address_id=self.address.id)

    async def prepare(self, principal=None, *, quantity=1, addons=False):
        principal = principal or self.cart.guest
        await self.cart.service.create_cart(principal, self.cart.branch)
        return await self.cart.service.add_item(
            principal,
            ItemCreate(
                product_id=self.cart.product.id,
                presentation_id=self.cart.personal.id,
                quantity=quantity,
                notes=None,
                addons=(CartAddonSelection(self.cart.addon.id, (self.cart.paid.id,)),)
                if addons
                else (),
            ),
        )

    def fork(self):
        session = MemoryOrderSession(self.store)
        return session, OrderService(
            session, session, session, session, session, session, lambda: self.now
        )


async def orders_setup():
    cart = await cart_setup()
    store = Store(cart)
    now = datetime(2026, 10, 6, 17, 0, tzinfo=UTC)
    table = RestaurantTable(branch_id=cart.branch, label="Mesa Test")
    store.tables[table.id] = table
    for principal in (cart.guest, cart.registered):
        store.customers[principal.customer_id] = CustomerSnapshot(
            id=principal.customer_id,
            full_name="Customer original",
            phone="+51900000111",
        )
    address = AddressSnapshot(
        id=uuid4(),
        recipient_name="Recipient original",
        recipient_phone="+51900000112",
        address_line="Test address 123",
        reference_text="Test reference",
        district="Tarapoto",
        city="Tarapoto",
        department="San Martín",
        latitude=Decimal("-6.483333"),
        longitude=None,
    )
    store.addresses[address.id] = (cart.guest.customer_id, address)
    for district in ("Tarapoto", "Morales", "La Banda de Shilcayo"):
        zone = DeliveryZone(
            branch_id=None,
            name=district,
            district=district,
            is_free=True,
            delivery_fee=Decimal("0.00"),
        )
        store.zones[zone.id] = zone
    for permission in ("ORDER_MANAGE", "ORDER_SETTINGS_MANAGE"):
        store.grants.add((cart.admin.user_id, cart.branch, permission))
    session = MemoryOrderSession(store)
    service = OrderService(
        session, session, session, session, session, session, lambda: now
    )
    setup = OrdersSetup(
        cart,
        store,
        session,
        service,
        OrderSettingsService(session, session),
        table,
        address,
        now,
    )
    await setup.prepare()
    return setup
