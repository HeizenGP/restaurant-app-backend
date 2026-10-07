"""Phase 8 test adapters, never imported by production. Serialized memory is not PG."""

import copy
from dataclasses import asdict, dataclass, field, replace
from types import SimpleNamespace
from uuid import uuid4

from app.modules.cancellations.application.services import CancellationService
from app.modules.cancellations.domain.models import RequestStatus
from app.modules.orders.domain.cancellations import (
    OrderCancellationContext,
    validate_cancellation,
)
from app.modules.orders.domain.models import OrderStatus, PaymentMethodType
from app.modules.orders.domain.models import PaymentStatus as OrderPaid
from app.modules.payments.application.refund_dtos import (
    RefundAttemptLocator,
    RefundAttemptResult,
    RefundView,
    VerifiedRefundEvent,
)
from app.modules.payments.application.refund_errors import (
    RefundDataError,
    RefundWebhookAuthenticationError,
)
from app.modules.payments.application.refund_registration import (
    RefundRegistrationService,
)
from app.modules.payments.application.refund_services import RefundService
from app.modules.payments.application.services import PaymentService
from app.modules.payments.domain.models import (
    ACTIVE_ATTEMPT_STATUSES,
    AttemptStatus,
    Payment,
    PaymentAttempt,
    PaymentStatus,
)
from tests.modules.payments.fakes import (
    NOW,
    MemoryDatabase,
    MemoryOrders,
    MemoryPaymentRepository,
    TestGateway,
    payment_setup,
)


@dataclass
class Backend(MemoryDatabase):
    requests: dict = field(default_factory=dict)
    cancellations: dict = field(default_factory=dict)
    assignments: dict = field(default_factory=dict)
    refund_attempts: dict = field(default_factory=dict)
    refund_events: dict = field(default_factory=dict)
    audits: list = field(default_factory=list)


class Unit:
    def __init__(self, db):
        self.db, self.snapshot, self.fail = db, None, None

    async def begin(self):
        if self.snapshot is None:
            await self.db.mutex.acquire()
            self.snapshot = copy.deepcopy(
                {k: v for k, v in vars(self.db).items() if k not in {"mutex", "trace"}}
            )

    def check(self, step):
        if self.fail == step:
            raise RuntimeError("Injected test failure")

    async def commit(self):
        self.check("commit")
        if self.snapshot is not None:
            self.snapshot = None
            self.db.mutex.release()

    async def rollback(self):
        if self.snapshot is not None:
            for k, v in self.snapshot.items():
                setattr(self.db, k, v)
            self.snapshot = None
            self.db.mutex.release()


class Adapter:
    def __init__(self, unit):
        self.unit, self.db = unit, unit.db

    async def commit(self):
        await self.unit.commit()

    async def rollback(self):
        await self.unit.rollback()


class Requests(Adapter):
    async def pending_request(self, order_id):
        return next(
            (
                r
                for r in self.db.requests.values()
                if r.order_id == order_id and r.status == RequestStatus.PENDING
            ),
            None,
        )

    async def request(self, branch, request_id, *, lock):
        if lock:
            await self.unit.begin()
        r = self.db.requests.get(request_id)
        return r if r and r.branch_id == branch else None

    async def insert_request(self, r):
        self.unit.check("request")
        assert await self.pending_request(r.order_id) is None
        self.db.requests[r.id] = r

    async def save_request(self, old, new):
        self.unit.check("request")
        assert self.db.requests[old.id] == old
        self.db.requests[old.id] = new
        return new

    async def list_owned(self, customer, order, limit, offset):
        rs = [
            r
            for r in self.db.requests.values()
            if r.customer_id == customer and r.order_id == order
        ]
        return sorted(rs, key=lambda r: (r.requested_at, r.id), reverse=True)[
            offset : offset + limit
        ]

    async def list_branch(self, branch, status, limit, offset):
        rs = [
            r
            for r in self.db.requests.values()
            if r.branch_id == branch and (status is None or r.status == status)
        ]
        return sorted(rs, key=lambda r: (r.requested_at, r.id))[offset : offset + limit]

    async def cancellation(self, order):
        return self.db.cancellations.get(order)

    async def insert_cancellation(self, c):
        self.unit.check("cancellation")
        assert c.order_id not in self.db.cancellations
        self.db.cancellations[c.order_id] = c


class Orders(Adapter):
    async def _get(self, order, scope, kind, lock):
        if lock:
            await self.unit.begin()
        value = self.db.orders.get(order)
        if value is None or getattr(value, kind) != scope:
            return None
        return OrderCancellationContext(
            **{
                k: getattr(value, k)
                for k in OrderCancellationContext.__dataclass_fields__
            }
        )

    async def owned(self, customer, order, *, lock):
        return await self._get(order, customer, "customer_id", lock)

    async def scoped(self, branch, order, *, lock):
        return await self._get(order, branch, "branch_id", lock)

    async def cancel(self, order, actor, now, reason):
        validate_cancellation(order)
        self.unit.check("order")
        old = self.db.orders[order.id]
        assert old.status == order.status
        self.db.orders[order.id] = replace(old, status=OrderStatus.CANCELLED)
        self.db.order_histories.append(
            (order.id, order.status, OrderStatus.CANCELLED, actor, reason)
        )


class Refunds(Adapter):
    async def refund_for_order(self, order_id, *, lock):
        if lock:
            await self.unit.begin()
        return next(
            (r for r in self.db.refunds.values() if r.order_id == order_id), None
        )

    async def insert_refund(self, r):
        self.unit.check("refund")
        assert await self.refund_for_order(r.order_id, lock=False) is None
        self.db.refunds[r.id] = r

    async def append_history(self, h):
        self.unit.check("history")
        self.db.refund_histories.append(h)

    async def owned(self, customer, order):
        o = self.db.orders.get(order)
        return (
            await self.refund_for_order(order, lock=False)
            if o and o.customer_id == customer
            else None
        )

    async def scoped(self, branch, refund_id, *, lock):
        if lock:
            await self.unit.begin()
        r = self.db.refunds.get(refund_id)
        o = self.db.orders.get(r.order_id) if r else None
        return r if o and o.branch_id == branch else None

    async def lock_refund(self, refund_id):
        await self.unit.begin()
        return self.db.refunds.get(refund_id)

    async def list_branch(self, branch, status, method, limit, offset):
        rs = [
            r
            for r in self.db.refunds.values()
            if self.db.orders[r.order_id].branch_id == branch
            and (status is None or r.status == status)
            and (method is None or r.method_type == method)
        ]
        return sorted(rs, key=lambda r: (r.requested_at, r.id))[offset : offset + limit]

    async def view(self, r):
        return RefundView(
            refund=r,
            attempts=tuple(
                a for a in self.db.refund_attempts.values() if a.refund_id == r.id
            ),
            history=tuple(h for h in self.db.refund_histories if h.refund_id == r.id),
        )

    async def save_refund(self, old, new):
        self.unit.check("refund")
        assert self.db.refunds[old.id] == old
        self.db.refunds[old.id] = new
        return new

    async def successful_capture(self, payment):
        values = [
            a
            for a in self.db.attempts.values()
            if a.payment_id == payment and a.status == AttemptStatus.SUCCEEDED
        ]
        return values[0] if len(values) == 1 else None

    async def insert_attempt(self, a):
        assert await self.active_attempt(a.refund_id) is None
        assert await self.attempt_by_key(a.refund_id, a.idempotency_key) is None
        self.db.refund_attempts[a.id] = a

    async def save_attempt(self, old, new):
        self.unit.check("attempt")
        assert self.db.refund_attempts[old.id] == old
        self.db.refund_attempts[old.id] = new
        return new

    async def attempt_by_key(self, refund, key):
        return next(
            (
                a
                for a in self.db.refund_attempts.values()
                if a.refund_id == refund and a.idempotency_key == key
            ),
            None,
        )

    async def active_attempt(self, refund):
        return next(
            (
                a
                for a in self.db.refund_attempts.values()
                if a.refund_id == refund and a.status in ACTIVE_ATTEMPT_STATUSES
            ),
            None,
        )

    async def attempt_by_id(self, refund, attempt, *, lock):
        if lock:
            await self.unit.begin()
        a = self.db.refund_attempts.get(attempt)
        return a if a and a.refund_id == refund else None

    async def attempt_locator(self, provider, reference):
        a = next(
            (
                a
                for a in self.db.refund_attempts.values()
                if a.provider_code == provider and a.provider_reference == reference
            ),
            None,
        )
        return (
            RefundAttemptLocator(refund_id=a.refund_id, attempt_id=a.id) if a else None
        )

    async def get_or_insert_event(self, e):
        await self.unit.begin()
        return self.db.refund_events.setdefault(
            (e.provider_code, e.provider_event_id), e
        )

    async def save_event(self, old, new):
        self.db.refund_events[(old.provider_code, old.provider_event_id)] = new


class Registration(Adapter):
    async def register_if_paid(self, order, now):
        p = next((p for p in self.db.payments.values() if p.order_id == order.id), None)
        if order.payment_status != OrderPaid.PAID:
            if p and p.status == PaymentStatus.PAID:
                raise RefundDataError()
            return None
        if p is None:
            raise RefundDataError()
        return await RefundRegistrationService(Refunds(self.unit)).register_full(
            p, order.id, order.total, order.payment_method_type, now
        )

    async def for_order(self, order_id):
        return await Refunds(self.unit).refund_for_order(order_id, lock=False)


class Cleanup(Adapter):
    async def close_assignment(self, order, actor, now):
        self.unit.check("assignment")
        for key, a in list(self.db.assignments.items()):
            if a.order_id == order and a.unassigned_at is None:
                self.db.assignments[key] = replace(
                    a,
                    unassigned_at=now,
                    unassigned_by_user_id=actor,
                    reason="Order cancelled",
                )


class Audit(Adapter):
    async def record(self, record):
        self.unit.check("audit")
        self.db.audits.append(record)


class Payments(MemoryPaymentRepository):
    def __init__(self, unit):
        super().__init__(unit.db)
        self.unit = unit

    async def begin(self):
        await self.unit.begin()

    async def commit(self):
        await self.unit.commit()

    async def rollback(self):
        await self.unit.rollback()

    async def ensure_cancelled_refund(self, order, payment, now):
        await RefundRegistrationService(Refunds(self.unit)).register_full(
            payment, order.id, order.total, order.payment_method_type, now
        )


class RefundGateway(TestGateway):
    def __init__(self, db):
        super().__init__(db)
        self.result = AttemptStatus.PROCESSING

    async def refund(self, request):
        assert not self.db.mutex.locked(), "External I/O under a transaction lock"
        self.calls.append(request)
        if self.timeout:
            raise TimeoutError("Private provider detail")
        result = self.operations.setdefault(
            request.provider_idempotency_key,
            RefundAttemptResult(
                provider_code=self.provider_code,
                provider_reference="refund_" + str(request.attempt_id),
                status=self.result,
                failure_code="DECLINED"
                if self.result == AttemptStatus.FAILED
                else None,
            ),
        )
        if self.before_return:
            await self.before_return()
        return result

    async def verify_and_parse_webhook(self, provider, body, headers):
        try:
            e = await super().verify_and_parse_webhook(provider, body, headers)
        except Exception:
            raise RefundWebhookAuthenticationError() from None
        return VerifiedRefundEvent(**asdict(e))


def cancellation_setup(*, paid=True, method=PaymentMethodType.ONLINE, total=None):
    original = payment_setup()
    db = Backend()
    unit = Unit(db)
    order = replace(
        original.order,
        status=OrderStatus.WAITING if paid else OrderStatus.PENDING_PAYMENT,
        payment_status=OrderPaid.PAID if paid else OrderPaid.PENDING,
        payment_method_type=method,
        confirmed_at=NOW if paid else None,
        total=total if total is not None else original.order.total,
    )
    db.orders[order.id] = order
    if paid:
        p = Payment(
            order_id=order.id,
            amount=order.total,
            method_type=method,
            status=PaymentStatus.PAID,
            paid_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        db.payments[p.id] = p
        if method == PaymentMethodType.ONLINE:
            a = PaymentAttempt(
                payment_id=p.id,
                idempotency_key="original-capture",
                provider_code="test_gateway",
                provider_reference="capture_" + str(uuid4()),
                amount=p.amount,
                status=AttemptStatus.SUCCEEDED,
                completed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
            db.attempts[a.id] = a
    authz = original.authz
    for permission in ("CANCELLATION_VIEW", "CANCELLATION_MANAGE", "REFUND_MANAGE"):
        authz.grants.add((original.admin.user_id, order.branch_id, permission))
    repo = Requests(unit)
    gateway = RefundGateway(db)
    payment_repo = Payments(unit)
    payment_gateway = TestGateway(db)
    return SimpleNamespace(
        db=db,
        unit=unit,
        repo=repo,
        branch=order.branch_id,
        order=order,
        customer=original.customer,
        guest=original.guest,
        foreign=original.foreign,
        admin=original.admin,
        kitchen=original.kitchen,
        authz=authz,
        gateway=gateway,
        service=CancellationService(
            repo,
            Orders(unit),
            authz,
            Registration(unit),
            Cleanup(unit),
            Audit(unit),
            clock=lambda: NOW,
        ),
        refund_service=RefundService(
            Refunds(unit), authz, gateway, Audit(unit), clock=lambda: NOW
        ),
        payment_service=PaymentService(
            payment_repo,
            MemoryOrders(payment_repo),
            authz,
            payment_gateway,
            lambda: NOW,
        ),
        payment_gateway=payment_gateway,
    )
