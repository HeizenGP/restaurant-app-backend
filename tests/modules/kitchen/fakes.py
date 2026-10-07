import asyncio
from copy import deepcopy
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.kitchen.application.services import KitchenService
from app.modules.kitchen.domain.models import (
    KITCHEN_STATUSES,
    KitchenAddon,
    KitchenItem,
    KitchenOrderSnapshot,
    target_ready_status,
)
from app.modules.orders.domain.lifecycle import (
    OrderTransitionContext,
    validate_preparation_transition,
)
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)

NOW = datetime(2026, 10, 6, 12, 20, tzinfo=UTC)
WAITING_AT = NOW - timedelta(minutes=20)
PREPARING_AT = NOW - timedelta(minutes=16)
READY_AT = NOW - timedelta(minutes=9)


def record(
    *,
    branch_id=None,
    mode=OrderMode.LOCAL,
    status=OrderStatus.WAITING,
    number=1,
    payment_status=None,
    confirmed=True,
):
    payment = (
        PaymentMethodType.CASH if mode == OrderMode.LOCAL else PaymentMethodType.ONLINE
    )
    paid = (
        PaymentStatus.PENDING
        if payment == PaymentMethodType.CASH
        else PaymentStatus.PAID
    )
    route = (
        (OrderStatus.WAITING, WAITING_AT),
        (OrderStatus.PREPARING, PREPARING_AT),
        (target_ready_status(mode), READY_AT),
    )
    histories = []
    previous = None
    for stage, timestamp in route:
        if status not in KITCHEN_STATUSES:
            break
        histories.append(
            StatusHistory(from_status=previous, to_status=stage, created_at=timestamp)
        )
        previous = stage
        if stage == status:
            break
    if status not in KITCHEN_STATUSES:
        histories = [
            StatusHistory(from_status=None, to_status=status, created_at=WAITING_AT)
        ]
    return SimpleNamespace(
        id=uuid4(),
        order_number=number,
        branch_id=branch_id or uuid4(),
        mode=mode,
        status=status,
        payment_method_type=payment,
        payment_status=payment_status or paid,
        created_at=WAITING_AT - timedelta(hours=3),
        confirmed_at=WAITING_AT if confirmed else None,
        items=(
            KitchenItem(
                product_name_snapshot="Aeropuerto original",
                presentation_name_snapshot="Familiar original",
                quantity=2,
                notes="Sin cebolla",
                addon_options=(
                    KitchenAddon(
                        addon_name_snapshot="Extras original",
                        option_name_snapshot="Wantán original",
                    ),
                ),
            ),
        ),
        history=tuple(histories),
        table_label="Mesa 05" if mode == OrderMode.LOCAL else None,
        requested_pickup_at=NOW + timedelta(hours=1)
        if mode == OrderMode.PICKUP
        else None,
        estimated_ready_at=NOW + timedelta(minutes=55)
        if mode == OrderMode.PICKUP
        else None,
        estimated_delivery_at=NOW + timedelta(minutes=30)
        if mode == OrderMode.DELIVERY
        else None,
    )


def context(row):
    return OrderTransitionContext(
        **{
            field.name: getattr(row, field.name)
            for field in fields(OrderTransitionContext)
        }
    )


def snapshot(row):
    return KitchenOrderSnapshot(
        **{
            field.name: getattr(row, field.name)
            for field in fields(KitchenOrderSnapshot)
        }
    )


class Store:
    def __init__(self):
        self.orders = {}
        self.locks = {}
        self.commits = 0
        self.rollbacks = 0
        self.transitions = 0

    def add(self, row):
        self.orders[row.id] = row
        self.locks[row.id] = asyncio.Lock()
        return row


class MemoryKitchenOrders:
    def __init__(self, store):
        self.store = store
        self.before = None
        self.locked = None
        self.fail_history = False
        self.fail_commit = False
        self.calls = []

    def fork(self):
        return MemoryKitchenOrders(self.store)

    @staticmethod
    def operative(row):
        return (
            row.status in KITCHEN_STATUSES
            and row.confirmed_at is not None
            and (
                row.payment_method_type == PaymentMethodType.CASH
                or row.payment_status == PaymentStatus.PAID
            )
        )

    async def queue(self, branch_id, query):
        self.calls.append("queue")
        orders = [
            snapshot(row)
            for row in self.store.orders.values()
            if row.branch_id == branch_id
            and self.operative(row)
            and (query.mode is None or row.mode == query.mode)
            and (query.status is None or row.status == query.status)
        ]

        def key(row):
            column = (
                0
                if row.status == OrderStatus.WAITING
                else 1
                if row.status == OrderStatus.PREPARING
                else 2
            )
            entered = max(
                (
                    entry.created_at
                    for entry in row.history
                    if entry.to_status == row.status
                ),
                default=datetime.min.replace(tzinfo=UTC),
            )
            return column, entered, row.order_number, row.id

        orders.sort(key=key)
        return orders[query.offset : query.offset + query.limit + 1]

    async def get_order(self, branch_id, order_id):
        self.calls.append("get")
        row = self.store.orders.get(order_id)
        return (
            snapshot(row)
            if row and row.branch_id == branch_id and self.operative(row)
            else None
        )

    async def lock_order(self, branch_id, order_id):
        self.calls.append("lock")
        row = self.store.orders.get(order_id)
        if row is None or row.branch_id != branch_id:
            return None
        await self.store.locks[order_id].acquire()
        self.locked = order_id
        self.before = deepcopy(self.store.orders[order_id])
        await asyncio.sleep(0)
        return context(self.store.orders[order_id])

    async def record_preparation_transition(self, order, history):
        self.calls.append("transition")
        validate_preparation_transition(order, history)
        row = self.store.orders[order.id]
        assert self.locked == order.id and row.status == order.status
        row.status = history.to_status
        await asyncio.sleep(0)
        if self.fail_history:
            raise RuntimeError("Simulated history insert failure")
        row.history = (*row.history, history)
        self.store.transitions += 1

    def close(self):
        if self.locked is not None:
            self.store.locks[self.locked].release()
            self.locked = None

    async def commit(self):
        self.calls.append("commit")
        if self.fail_commit:
            raise RuntimeError("Simulated commit failure")
        self.store.commits += 1
        self.close()

    async def rollback(self):
        self.calls.append("rollback")
        self.store.rollbacks += 1
        if self.locked is not None:
            self.store.orders[self.locked] = deepcopy(self.before)
        self.close()


class MemoryAuthorization:
    def __init__(self):
        self.grants = set()
        self.inactive = set()
        self.ended = set()
        self.blocked = set()
        self.deleted = set()
        self.inactive_branches = set()
        self.calls = []

    async def has_permission(self, user_id, branch_id, permission):
        self.calls.append((user_id, branch_id, permission))
        return (
            (user_id, branch_id, permission) in self.grants
            and user_id not in self.inactive | self.ended | self.blocked | self.deleted
            and branch_id not in self.inactive_branches
        )


@dataclass
class KitchenSetup:
    store: Store
    gateway: MemoryKitchenOrders
    authorization: MemoryAuthorization
    branch: UUID
    user: Principal
    admin: Principal
    customer: Principal
    guest: Principal
    foreign: Principal
    service: KitchenService
    row: SimpleNamespace
    now: datetime = NOW

    def fork(self):
        gateway = self.gateway.fork()
        return gateway, KitchenService(
            gateway, self.authorization, clock=lambda: self.now
        )


def kitchen_setup():
    store = Store()
    gateway = MemoryKitchenOrders(store)
    authorization = MemoryAuthorization()
    branch = uuid4()

    def user():
        return Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())

    cook, admin, foreign = user(), user(), user()
    for actor in (cook, admin):
        for permission in ("KITCHEN_VIEW", "KITCHEN_MANAGE"):
            authorization.grants.add((actor.user_id, branch, permission))
    customer = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    guest = Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())
    row = store.add(record(branch_id=branch))
    setup = KitchenSetup(
        store,
        gateway,
        authorization,
        branch,
        cook,
        admin,
        customer,
        guest,
        foreign,
        KitchenService(gateway, authorization, clock=lambda: NOW),
        row,
    )
    return setup
