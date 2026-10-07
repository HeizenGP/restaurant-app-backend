"""Test-only adapters. Memory locks are not evidence of PostgreSQL concurrency."""

import asyncio
import copy
from dataclasses import dataclass, field, replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.notifications.application.dtos import (
    AdminSnapshot,
    NotificationPage,
    PushClaim,
    PushResult,
    StreamBatch,
)
from app.modules.notifications.application.errors import (
    DeviceBusyError,
    DeviceConflictError,
    RealtimePermissionError,
)
from app.modules.notifications.application.services import NotificationService
from app.modules.notifications.domain.models import (
    DevicePlatform,
    Notification,
    NotificationDevice,
    NotificationKind,
    NotificationSource,
    PushDelivery,
    PushResultKind,
    RealtimeEventType,
    RealtimeOrderEvent,
    retry_seconds,
)
from app.modules.notifications.domain.models import (
    PushDeliveryStatus as S,
)
from app.modules.notifications.infrastructure.push_gateway import (
    ConfiguredPushGatewayRegistry,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus
from tests.modules.payments.fakes import NOW


@dataclass
class Store:
    notifications: dict = field(default_factory=dict)
    devices: dict = field(default_factory=dict)
    deliveries: dict = field(default_factory=dict)
    events: dict = field(default_factory=dict)
    snapshots: list = field(default_factory=list)
    grants: set = field(default_factory=set)
    mutex: asyncio.Lock = field(default_factory=asyncio.Lock)


def notification(customer=None, branch=None, sequence=1, **values):
    order = values.pop("order_id", uuid4())
    kind = values.get("kind", NotificationKind.ORDER_RECEIVED)
    source = (
        NotificationSource.ORDER
        if kind == NotificationKind.ORDER_RECEIVED
        else NotificationSource.DELIVERY_DELAY_INCIDENT
        if kind == NotificationKind.DELIVERY_DELAYED
        else NotificationSource.ORDER_STATUS_HISTORY
    )
    return Notification(
        **(
            dict(
                id=uuid4(),
                sequence_id=sequence,
                customer_id=customer or uuid4(),
                order_id=order,
                branch_id=branch or uuid4(),
                kind=kind,
                order_number_snapshot=123,
                order_status=OrderStatus.WAITING,
                source_kind=source,
                source_id=order if source == NotificationSource.ORDER else uuid4(),
                created_at=NOW,
            )
            | values
        )
    )


def device(customer=None, **values):
    return NotificationDevice(
        **(
            dict(
                id=uuid4(),
                installation_id=uuid4(),
                customer_id=customer or uuid4(),
                platform=DevicePlatform.ANDROID,
                provider_code="test",
                push_token="test-only-opaque-token",
                is_active=True,
                generation=1,
                last_seen_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
            | values
        )
    )


def delivery(n=None, d=None, **values):
    n, d = n or notification(), d or device()
    return PushDelivery(
        **(
            dict(
                id=uuid4(),
                notification_id=n.id,
                device_id=d.id,
                provider_code=d.provider_code,
                device_generation=d.generation,
                status=S.PENDING,
                attempt_count=0,
                next_attempt_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
            | values
        )
    )


def event(branch=None, identifier=1, **values):
    return RealtimeOrderEvent(
        **(
            dict(
                id=identifier,
                branch_id=branch or uuid4(),
                order_id=uuid4(),
                order_number=123,
                mode=OrderMode.LOCAL,
                event_type=RealtimeEventType.ORDER_CREATED,
                status=OrderStatus.WAITING,
                payment_status=PaymentStatus.PENDING,
                status_changed=False,
                payment_status_changed=False,
                occurred_at=NOW,
            )
            | values
        )
    )


def enqueue(store, n):
    """Fixtures model capture-time device membership, not production SQL triggers."""
    if any(
        (x.source_kind, x.source_id, x.kind) == (n.source_kind, n.source_id, n.kind)
        for x in store.notifications.values()
    ):
        return
    store.notifications[n.id] = n
    for d in store.devices.values():
        if d.customer_id == n.customer_id and d.is_active:
            p = delivery(n, d)
            store.deliveries[p.id] = p


def cancel_device(store, identifier):
    for p in list(store.deliveries.values()):
        if p.device_id == identifier and p.status in {S.PENDING, S.PROCESSING}:
            store.deliveries[p.id] = replace(
                p,
                status=S.CANCELLED,
                locked_until=None,
                claim_token=None,
                failure_code="DEVICE_CHANGED",
            )


class MemoryRepository:
    def __init__(self, store):
        self.store, self.backup = store, None
        self.commits = self.rollbacks = 0
        self.fail_commit = False
        self.released = False

    def begin(self):
        if self.backup is None:
            self.backup = copy.deepcopy(
                {k: v for k, v in vars(self.store).items() if k != "mutex"}
            )

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("Injected commit failure")
        self.backup = None
        self.commits += 1

    async def rollback(self):
        if self.backup is not None:
            for k, v in self.backup.items():
                setattr(self.store, k, v)
        self.backup = None
        self.rollbacks += 1
        self.released = True

    async def high_watermark(self, *, customer=None, branch=None):
        values = (
            [
                n.sequence_id
                for n in self.store.notifications.values()
                if n.customer_id == customer
            ]
            if customer is not None
            else [e.id for e in self.store.events.values() if e.branch_id == branch]
        )
        return max(values, default=0)

    async def list_owned(self, customer, before, limit):
        rows = sorted(
            (
                n
                for n in self.store.notifications.values()
                if n.customer_id == customer
                and (before is None or n.sequence_id < before)
            ),
            key=lambda n: n.sequence_id,
            reverse=True,
        )
        return NotificationPage(
            items=tuple(rows[:limit]),
            latest_sequence_id=await self.high_watermark(customer=customer),
            next_before_sequence_id=rows[limit - 1].sequence_id
            if len(rows) > limit
            else None,
        )

    async def unread_count(self, customer):
        return sum(
            n.customer_id == customer and n.read_at is None
            for n in self.store.notifications.values()
        )

    async def mark_read(self, customer, identifier, now):
        self.begin()
        n = self.store.notifications.get(identifier)
        if n is None or n.customer_id != customer:
            return None
        if n.read_at is None:
            n = replace(n, read_at=max(now, n.created_at))
            self.store.notifications[n.id] = n
        return n

    async def mark_all_read(self, customer, now):
        self.begin()
        count = 0
        for n in list(self.store.notifications.values()):
            if n.customer_id == customer and n.read_at is None:
                self.store.notifications[n.id] = replace(
                    n, read_at=max(now, n.created_at)
                )
                count += 1
        return count

    async def register_device(
        self, customer, installation, platform, provider, token, now
    ):
        self.begin()
        old = next(
            (
                d
                for d in self.store.devices.values()
                if d.installation_id == installation
            ),
            None,
        )
        if any(
            d.provider_code == provider
            and d.push_token == token
            and d.installation_id != installation
            for d in self.store.devices.values()
        ):
            raise DeviceConflictError()
        if old is None:
            new = device(
                customer,
                installation_id=installation,
                platform=platform,
                provider_code=provider,
                push_token=token,
                last_seen_at=now,
            )
        else:
            changed = (
                old.customer_id,
                old.platform,
                old.provider_code,
                old.push_token,
                old.is_active,
            ) != (customer, platform, provider, token, True)
            if changed and old.send_locked_until and old.send_locked_until > now:
                raise DeviceBusyError()
            if changed:
                cancel_device(self.store, old.id)
            new = replace(
                old,
                customer_id=customer,
                platform=platform,
                provider_code=provider,
                push_token=token,
                is_active=True,
                last_seen_at=now,
                updated_at=now,
                generation=old.generation + int(changed),
                send_locked_until=None if changed else old.send_locked_until,
            )
        self.store.devices[new.id] = new
        return new

    async def unregister_device(self, customer, installation, now):
        self.begin()
        old = next(
            (
                d
                for d in self.store.devices.values()
                if d.installation_id == installation and d.customer_id == customer
            ),
            None,
        )
        if old is None:
            return False
        if old.is_active:
            self.store.devices[old.id] = replace(
                old, is_active=False, generation=old.generation + 1, updated_at=now
            )
            cancel_device(self.store, old.id)
        return True

    async def events(self, branch, after, limit, until=None):
        return sorted(
            (
                e
                for e in self.store.events.values()
                if e.branch_id == branch
                and e.id > after
                and (until is None or e.id <= until)
            ),
            key=lambda e: e.id,
        )[:limit]

    async def stream_notifications(self, customer, after, until, limit):
        return sorted(
            (
                n
                for n in self.store.notifications.values()
                if n.customer_id == customer and after < n.sequence_id <= until
            ),
            key=lambda n: n.sequence_id,
        )[:limit]

    async def admin_snapshot(self, branch, status, after_number, limit):
        terminals = {
            OrderStatus.CANCELLED,
            OrderStatus.SERVED,
            OrderStatus.PICKED_UP,
            OrderStatus.DELIVERED,
        }
        rows = sorted(
            (
                o
                for b, o in self.store.snapshots
                if b == branch
                and o.order_number > after_number
                and (o.status == status if status else o.status not in terminals)
            ),
            key=lambda o: o.order_number,
        )
        return AdminSnapshot(
            orders=tuple(rows[:limit]),
            latest_event_id=await self.high_watermark(branch=branch),
            next_after_order_number=rows[limit - 1].order_number
            if len(rows) > limit
            else None,
        )


class Authorization:
    def __init__(self, store):
        self.store = store

    async def has_permission(self, user, branch, permission):
        return (user, branch, permission) in self.store.grants


class TestGateway:
    __test__ = False
    provider_code = "test"

    def __init__(self, result=None):
        self.result = result or PushResult(kind=PushResultKind.SENT)
        self.messages = []
        self.hook = None

    async def send(self, message):
        self.messages.append(message)
        if self.hook:
            await self.hook(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class MemoryPushRepository:
    def __init__(self, store):
        self.store = store
        self.claim_calls = 0
        self.in_transaction = False

    async def claim(self, providers, now, limit):
        self.claim_calls += 1
        claims = []
        async with self.store.mutex:
            self.in_transaction = True
            try:
                for p in list(self.store.deliveries.values()):
                    if len(claims) >= limit:
                        break
                    d = self.store.devices[p.device_id]
                    n = self.store.notifications[p.notification_id]
                    if p.provider_code not in providers or (
                        d.send_locked_until and d.send_locked_until > now
                    ):
                        continue
                    if not (
                        (p.status == S.PENDING and p.next_attempt_at <= now)
                        or (p.status == S.PROCESSING and p.locked_until < now)
                    ):
                        continue
                    if (
                        not d.is_active
                        or d.customer_id != n.customer_id
                        or d.generation != p.device_generation
                    ):
                        cancel_device(self.store, d.id)
                        continue
                    if p.attempt_count >= 5:
                        self.store.deliveries[p.id] = replace(
                            p,
                            status=S.FAILED,
                            locked_until=None,
                            claim_token=None,
                            failure_code="MAX_ATTEMPTS",
                        )
                        continue
                    p = replace(
                        p,
                        status=S.PROCESSING,
                        attempt_count=p.attempt_count + 1,
                        locked_until=now + timedelta(seconds=120),
                        claim_token=uuid4(),
                        failure_code=None,
                    )
                    self.store.deliveries[p.id] = p
                    self.store.devices[d.id] = replace(
                        d, send_locked_until=p.locked_until
                    )
                    claims.append(PushClaim(delivery=p, device=d, notification=n))
            finally:
                self.in_transaction = False
        return claims

    async def can_send(self, claim, now):
        p = self.store.deliveries[claim.delivery.id]
        d = self.store.devices[p.device_id]
        return (
            p.status == S.PROCESSING
            and p.claim_token == claim.delivery.claim_token
            and p.locked_until > now
            and d.is_active
            and d.customer_id == claim.notification.customer_id
            and d.generation == p.device_generation
        )

    async def complete(self, claim, result, now):
        async with self.store.mutex:
            if not await self.can_send(claim, now):
                return None
            p = self.store.deliveries[claim.delivery.id]
            values = dict(locked_until=None, claim_token=None)
            if result.kind == PushResultKind.SENT:
                values |= dict(
                    status=S.SENT,
                    sent_at=now,
                    provider_message_id=result.provider_message_id,
                )
            elif result.kind in {
                PushResultKind.INVALID_TOKEN,
                PushResultKind.PERMANENT_FAILURE,
            }:
                values |= dict(status=S.FAILED, failure_code=result.kind.value)
            elif p.attempt_count >= 5:
                values |= dict(status=S.FAILED, failure_code="MAX_ATTEMPTS")
            else:
                values |= dict(
                    status=S.PENDING,
                    failure_code="RETRYABLE_FAILURE",
                    next_attempt_at=now
                    + timedelta(seconds=retry_seconds(p.attempt_count)),
                )
            p = replace(p, **values)
            self.store.deliveries[p.id] = p
            d = self.store.devices[p.device_id]
            if result.kind == PushResultKind.INVALID_TOKEN:
                self.store.devices[d.id] = replace(
                    d, is_active=False, generation=d.generation + 1
                )
                cancel_device(self.store, d.id)
            elif not any(
                x.device_id == d.id and x.status == S.PROCESSING
                for x in self.store.deliveries.values()
            ):
                self.store.devices[d.id] = replace(d, send_locked_until=None)
            return p.status


class Clock:
    def __init__(self, start=NOW):
        self.now, self.elapsed = start, 0.0

    def __call__(self):
        return self.now

    def monotonic(self):
        return self.elapsed

    def advance(self, seconds):
        self.elapsed += seconds
        self.now += timedelta(seconds=seconds)

    async def sleep(self, seconds):
        self.advance(seconds)
        await asyncio.sleep(0)


class MemoryStreamReader:
    def __init__(self, repo, *, resolve=None, decode=None, clock=None):
        self.repo, self.resolve, self.decode = repo, resolve, decode
        self.clock = clock or Clock()
        self.calls = []
        self.expires_at = self.clock() + timedelta(minutes=15)
        self.revoked = False

    async def read(self, scope, after, limit, *, revalidate):
        self.calls.append((after, limit, revalidate))
        if revalidate:
            if self.revoked:
                raise RealtimePermissionError()
            if self.resolve:
                assert await self.resolve(scope.credential) == scope.principal
                self.expires_at = self.decode(scope.credential).expires_at
            if (
                scope.branch_id is not None
                and (scope.principal.user_id, scope.branch_id, scope.permission)
                not in self.repo.store.grants
            ):
                raise RealtimePermissionError()
        latest = await self.repo.high_watermark(
            customer=scope.principal.customer_id if scope.branch_id is None else None,
            branch=scope.branch_id,
        )
        rows = (
            []
            if after is None
            else (
                await self.repo.stream_notifications(
                    scope.principal.customer_id, after, latest, limit
                )
                if scope.branch_id is None
                else await self.repo.events(scope.branch_id, after, limit, latest)
            )
        )
        return StreamBatch(
            items=tuple(rows), latest_id=latest, expires_at=self.expires_at
        )


def notification_setup():
    store = Store()
    customer = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    guest = Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())
    foreign = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    admin = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    kitchen = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    branch, other_branch = uuid4(), uuid4()
    store.grants |= {
        (admin.user_id, branch, "ORDER_REALTIME_VIEW"),
        (admin.user_id, branch, "KITCHEN_VIEW"),
        (kitchen.user_id, branch, "KITCHEN_VIEW"),
    }
    repo = MemoryRepository(store)
    gateway = TestGateway()
    registry = ConfiguredPushGatewayRegistry([gateway])
    clock = Clock()
    return SimpleNamespace(
        store=store,
        customer=customer,
        guest=guest,
        foreign=foreign,
        admin=admin,
        kitchen=kitchen,
        branch=branch,
        other_branch=other_branch,
        repo=repo,
        gateway=gateway,
        registry=registry,
        clock=clock,
        service=NotificationService(repo, Authorization(store), registry, clock=clock),
    )
