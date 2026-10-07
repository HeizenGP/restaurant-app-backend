import asyncio
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.fulfillment.application.services import FulfillmentService
from app.modules.fulfillment.domain.models import DELIVERY_OPERATIONAL_STATUSES
from app.modules.fulfillment.domain.policies import is_delayed
from app.modules.orders.domain.fulfillment import (
    OrderFulfillmentContext,
    validate_fulfillment_transition,
)
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
)

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)


@dataclass
class Store:
    orders: dict = field(default_factory=dict)
    assignments: dict = field(default_factory=dict)
    incidents: dict = field(default_factory=dict)
    histories: list = field(default_factory=list)
    audits: list = field(default_factory=list)
    grants: set = field(default_factory=set)
    staff: set = field(default_factory=set)
    settings: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    trace: list = field(default_factory=list)


class MemoryRepository:
    def __init__(self, store):
        self.store = store
        self.before = None
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self.fail_completion = False
        self.fail_history = False
        self.fail_audit = False

    async def begin(self):
        if self.before is None:
            await self.store.lock.acquire()
            self.before = deepcopy(
                {
                    k: getattr(self.store, k)
                    for k in (
                        "orders",
                        "assignments",
                        "incidents",
                        "histories",
                        "audits",
                    )
                }
            )

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("Simulated commit failure")
        self.commits += 1
        if self.before is not None:
            self.before = None
            self.store.lock.release()

    async def rollback(self):
        self.rollbacks += 1
        if self.before is not None:
            for k, v in self.before.items():
                setattr(self.store, k, v)
            self.before = None
            self.store.lock.release()

    async def active_assignments(self, order_ids):
        return {
            a.order_id: a
            for a in self.store.assignments.values()
            if a.order_id in order_ids and a.active
        }

    async def active_assignment(self, order_id, *, lock):
        self.store.trace.append("assignment")
        return next(
            (
                a
                for a in self.store.assignments.values()
                if a.order_id == order_id and a.active
            ),
            None,
        )

    async def insert_assignment(self, assignment):
        assert await self.active_assignment(assignment.order_id, lock=False) is None
        self.store.assignments[assignment.id] = assignment

    async def close_assignment(self, original, updated):
        if self.fail_completion and updated.completed_at is not None:
            raise RuntimeError("Simulated assignment completion failure")
        assert self.store.assignments[original.id] == original and original.active
        self.store.assignments[original.id] = updated
        return updated

    async def insert_incident(self, incident):
        if any(i.order_id == incident.order_id for i in self.store.incidents.values()):
            return False
        self.store.incidents[incident.id] = incident
        return True

    async def list_incidents(self, branch_id, status, limit, offset):
        rows = sorted(
            (
                i
                for i in self.store.incidents.values()
                if i.branch_id == branch_id
                and (status is None or i.decision_status == status)
            ),
            key=lambda i: (i.detected_at, i.id),
            reverse=True,
        )
        return rows[offset : offset + limit]

    async def lock_incident(self, branch_id, incident_id):
        await self.begin()
        i = self.store.incidents.get(incident_id)
        return i if i is not None and i.branch_id == branch_id else None

    async def save_decision(self, original, updated):
        assert self.store.incidents[original.id] == original
        self.store.incidents[original.id] = updated
        return updated


class MemoryOrders:
    def __init__(self, repo):
        self.repo = repo

    async def settings_and_queue(self, branch):
        settings = self.repo.store.settings[branch]
        depth = sum(
            o.branch_id == branch
            and o.status in {OrderStatus.WAITING, OrderStatus.PREPARING}
            for o in self.repo.store.orders.values()
        )
        return settings, depth

    @staticmethod
    def operational(o, branch, mode):
        return (
            o.branch_id == branch
            and o.mode == mode
            and o.payment_method_type == PaymentMethodType.ONLINE
            and o.payment_status == PaymentStatus.PAID
            and o.confirmed_at is not None
        )

    async def lock_order(self, branch_id, order_id):
        await self.repo.begin()
        self.repo.store.trace.append("order")
        o = self.repo.store.orders.get(order_id)
        return o if o and o.branch_id == branch_id else None

    async def pickup_candidates(
        self, branch_id, limit, offset=0, *, now=None, prep_minutes=None, lock=False
    ):
        if lock:
            await self.repo.begin()
        rows = sorted(
            (
                o
                for o in self.repo.store.orders.values()
                if self.operational(o, branch_id, OrderMode.PICKUP)
                and o.status == OrderStatus.SCHEDULED
                and (
                    now is None
                    or o.requested_pickup_at <= now + timedelta(minutes=prep_minutes)
                )
            ),
            key=lambda o: (o.requested_pickup_at, o.id),
        )
        return rows[offset : offset + limit]

    async def delivery_queue(self, branch_id, status, limit, offset):
        return sorted(
            (
                o
                for o in self.repo.store.orders.values()
                if self.operational(o, branch_id, OrderMode.DELIVERY)
                and o.status in DELIVERY_OPERATIONAL_STATUSES
                and (status is None or o.status == status)
            ),
            key=lambda o: (o.order_number, o.id),
        )[offset : offset + limit]

    async def delay_candidates(self, branch_id, now, limit, after_order_number):
        await self.repo.begin()
        return sorted(
            (
                o
                for o in self.repo.store.orders.values()
                if self.operational(o, branch_id, OrderMode.DELIVERY)
                and o.order_number > after_order_number
                and is_delayed(o, now)
            ),
            key=lambda o: o.order_number,
        )[:limit]

    async def transition(self, order, history):
        validate_fulfillment_transition(order, history)
        fields = {"status": history.to_status}
        timestamp = {
            OrderStatus.WAITING: "waiting_at",
            OrderStatus.OUT_FOR_DELIVERY: "dispatched_at",
            OrderStatus.DELIVERED: "delivered_at",
        }.get(history.to_status)
        if timestamp:
            fields[timestamp] = history.created_at
        if history.to_status == OrderStatus.DELIVERED:
            fields["delivered_history_count"] = 1
        self.repo.store.orders[order.id] = replace(order, **fields)
        if self.repo.fail_history:
            raise RuntimeError("Simulated history failure after status update")
        self.repo.store.histories.append((order.id, history))


class MemoryAuthorization:
    def __init__(self, store):
        self.store = store

    async def has_permission(self, user_id, branch_id, permission):
        return (user_id, branch_id, permission) in self.store.grants

    async def staff_is_active(self, user_id, branch_id, now):
        return (user_id, branch_id) in self.store.staff


class MemoryAudit:
    def __init__(self, repo):
        self.repo = repo

    async def record(self, event):
        if self.repo.fail_audit:
            raise RuntimeError("Simulated audit failure")
        self.repo.store.audits.append(event)


@dataclass
class Setup:
    store: Store
    repo: MemoryRepository
    orders: MemoryOrders
    authorization: MemoryAuthorization
    service: FulfillmentService
    branch: object
    admin: Principal
    kitchen: Principal
    customer: Principal
    guest: Principal
    foreign: Principal
    order: OrderFulfillmentContext
    now: datetime = NOW


def record(branch, mode=OrderMode.PICKUP, status=None, number=1, **changes):
    args = dict(
        id=uuid4(),
        branch_id=branch,
        order_number=number,
        mode=mode,
        status=status
        or (OrderStatus.SCHEDULED if mode == OrderMode.PICKUP else OrderStatus.READY),
        payment_method_type=PaymentMethodType.ONLINE,
        payment_status=PaymentStatus.PAID,
        confirmed_at=NOW - timedelta(minutes=60),
    )
    if mode == OrderMode.PICKUP:
        args.update(
            requested_pickup_at=NOW + timedelta(minutes=25),
            calculated_kitchen_release_at=NOW,
            estimated_ready_at=NOW + timedelta(minutes=20),
            pickup_name_snapshot="María López",
            pickup_phone_snapshot="+51999888777",
        )
    elif mode == OrderMode.DELIVERY:
        args.update(
            estimated_delivery_at=NOW - timedelta(minutes=20),
            delivery_zone_name_snapshot="Tarapoto",
            recipient_name_snapshot="Historical recipient",
            recipient_phone_snapshot="+51900000111",
            address_line_snapshot="Historical private address",
            district_snapshot="Tarapoto",
            city_snapshot="Tarapoto",
            department_snapshot="San Martín",
            reference_text_snapshot="Historical reference",
            waiting_at=NOW - timedelta(minutes=50),
            preparing_at=NOW - timedelta(minutes=40),
            ready_at=NOW - timedelta(minutes=30),
        )
        if args["status"] == OrderStatus.DELIVERED:
            args.update(delivered_at=NOW, delivered_history_count=1)
    return OrderFulfillmentContext(**(args | changes))


def fulfillment_setup():
    store = Store()
    repo = MemoryRepository(store)
    orders = MemoryOrders(repo)
    auth = MemoryAuthorization(store)
    branch = uuid4()
    store.settings[branch] = BranchOrderSettings(branch_id=branch)
    admin = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    kitchen = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    customer = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    guest = Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())
    foreign = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    store.staff = {(admin.user_id, branch), (kitchen.user_id, branch)}
    for permission in (
        "FULFILLMENT_VIEW",
        "FULFILLMENT_MANAGE",
        "DELIVERY_ASSIGN",
        "DELIVERY_DELAY_REVIEW",
    ):
        store.grants.add((admin.user_id, branch, permission))
    order = record(branch)
    store.orders[order.id] = order
    setup = Setup(
        store,
        repo,
        orders,
        auth,
        None,
        branch,
        admin,
        kitchen,
        customer,
        guest,
        foreign,
        order,
    )
    setup.service = FulfillmentService(
        repo, orders, auth, MemoryAudit(repo), clock=lambda: setup.now
    )
    return setup


def change_order(setup, **changes):
    setup.order = replace(setup.store.orders[setup.order.id], **changes)
    setup.store.orders[setup.order.id] = setup.order
    return setup.order


def delivery_order(setup, status=OrderStatus.READY, **changes):
    new = record(setup.branch, OrderMode.DELIVERY, status, **changes)
    del setup.store.orders[setup.order.id]
    setup.order = new
    setup.store.orders[new.id] = new
    return new
