"""Test-only transactional repository and gateway. Never wired into the app."""

import asyncio
import copy
import hashlib
import hmac
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
)
from app.modules.orders.domain.models import (
    PaymentStatus as OrdersPaid,
)
from app.modules.orders.domain.payments import (
    OrderPaymentContext,
    payment_confirmation_target,
)
from app.modules.payments.application.dtos import (
    AttemptLocator,
    GatewayAttemptResult,
    PaymentView,
    VerifiedPaymentEvent,
)
from app.modules.payments.application.errors import (
    PaymentEventInvalidError,
    PaymentWebhookAuthenticationError,
)
from app.modules.payments.application.services import PaymentService
from app.modules.payments.domain.models import (
    ACTIVE_ATTEMPT_STATUSES,
    AttemptStatus,
    ClientAction,
    VerifiedResult,
)

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
TEST_SECRET = b"payments-test-only-not-a-provider-production-signature"


@dataclass
class MemoryDatabase:
    refunds: dict = field(default_factory=dict)
    refund_histories: list = field(default_factory=list)
    orders: dict = field(default_factory=dict)
    payments: dict = field(default_factory=dict)
    attempts: dict = field(default_factory=dict)
    events: dict = field(default_factory=dict)
    histories: list = field(default_factory=list)
    order_histories: list = field(default_factory=list)
    mutex: asyncio.Lock = field(default_factory=asyncio.Lock)
    trace: list = field(default_factory=list)


class MemoryPaymentRepository:
    async def ensure_cancelled_refund(self, order, payment, now):
        from app.modules.payments.domain.refunds import (
            Refund,
            RefundHistorySource,
            RefundStatus,
            RefundStatusHistory,
            validate_full_refund,
        )

        validate_full_refund(payment, order.id, order.total, order.payment_method_type)
        if any(r.order_id == order.id for r in self.db.refunds.values()):
            return
        refund = Refund(
            payment_id=payment.id,
            order_id=order.id,
            amount=payment.amount,
            method_type=payment.method_type,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.refunds[refund.id] = refund
        self.db.refund_histories.append(
            RefundStatusHistory(
                refund_id=refund.id,
                from_status=None,
                to_status=RefundStatus.PENDING,
                source=RefundHistorySource.SYSTEM,
                created_at=now,
            )
        )

    def __init__(self, db):
        self.db = db
        self.snapshot = None
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self.fail_order = False

    async def begin(self):
        if self.snapshot is None:
            await self.db.mutex.acquire()
            self.snapshot = copy.deepcopy(
                {
                    key: getattr(self.db, key)
                    for key in (
                        "orders",
                        "refunds",
                        "refund_histories",
                        "payments",
                        "attempts",
                        "events",
                        "histories",
                        "order_histories",
                    )
                }
            )

    async def get_owned(self, customer_id, order_id):
        order = self.db.orders.get(order_id)
        if order is None or order.customer_id != customer_id:
            return None
        payment = await self.payment_for_order(order_id, lock=False)
        return await self.view(payment) if payment else None

    async def payment_for_order(self, order_id, *, lock):
        self.db.trace.append("payment")
        return next(
            (p for p in self.db.payments.values() if p.order_id == order_id), None
        )

    async def insert_payment(self, payment):
        assert not any(
            p.order_id == payment.order_id for p in self.db.payments.values()
        )
        self.db.payments[payment.id] = payment

    async def save_payment(self, original, updated):
        assert self.db.payments[original.id] == original
        self.db.payments[original.id] = updated
        return updated

    async def view(self, payment):
        attempts = sorted(
            (a for a in self.db.attempts.values() if a.payment_id == payment.id),
            key=lambda a: (a.created_at, a.id),
            reverse=True,
        )[:100]
        return PaymentView(payment=payment, attempts=tuple(attempts))

    async def insert_attempt(self, attempt):
        assert not any(
            a.payment_id == attempt.payment_id
            and (
                a.idempotency_key == attempt.idempotency_key
                or a.status in ACTIVE_ATTEMPT_STATUSES
            )
            for a in self.db.attempts.values()
        )
        self.db.attempts[attempt.id] = attempt

    async def save_attempt(self, original, updated):
        assert self.db.attempts[original.id] == original
        self.db.attempts[original.id] = updated
        return updated

    async def attempt_by_key(self, payment_id, key):
        return next(
            (
                a
                for a in self.db.attempts.values()
                if a.payment_id == payment_id and a.idempotency_key == key
            ),
            None,
        )

    async def active_attempt(self, payment_id):
        return next(
            (
                a
                for a in self.db.attempts.values()
                if a.payment_id == payment_id and a.status in ACTIVE_ATTEMPT_STATUSES
            ),
            None,
        )

    async def attempt_by_id(self, payment_id, attempt_id, *, lock):
        self.db.trace.append("attempt")
        a = self.db.attempts.get(attempt_id)
        return a if a and a.payment_id == payment_id else None

    async def attempt_locator(self, provider, reference):
        a = next(
            (
                a
                for a in self.db.attempts.values()
                if a.provider_code == provider and a.provider_reference == reference
            ),
            None,
        )
        if a is None:
            return None
        p = self.db.payments[a.payment_id]
        return AttemptLocator(attempt_id=a.id, payment_id=p.id, order_id=p.order_id)

    async def append_history(self, history):
        self.db.histories.append(history)

    async def get_or_insert_event(self, event):
        await self.begin()
        key = (event.provider_code, event.provider_event_id)
        self.db.events.setdefault(key, event)
        return self.db.events[key]

    async def save_event(self, original, updated):
        self.db.events[(original.provider_code, original.provider_event_id)] = updated

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("Test commit failed")
        self.commits += 1
        self.snapshot = None
        if self.db.mutex.locked():
            self.db.mutex.release()

    async def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None:
            for key, value in self.snapshot.items():
                setattr(self.db, key, value)
            self.snapshot = None
            self.db.mutex.release()


class MemoryOrders:
    def __init__(self, repo):
        self.repo = repo

    async def owned_context(self, customer_id, order_id, *, lock):
        o = self.repo.db.orders.get(order_id)
        if o is None or o.customer_id != customer_id:
            return None
        if lock:
            await self.repo.begin()
        self.repo.db.trace.append("order")
        return self.repo.db.orders[order_id]

    async def branch_context(self, branch_id, order_id, *, lock):
        o = self.repo.db.orders.get(order_id)
        if o is None or o.branch_id != branch_id:
            return None
        if lock:
            await self.repo.begin()
        self.repo.db.trace.append("order")
        return self.repo.db.orders[order_id]

    async def lock_context(self, order_id):
        await self.repo.begin()
        self.repo.db.trace.append("order")
        return self.repo.db.orders.get(order_id)

    async def confirm_paid(self, order, now, *, online):
        if self.repo.fail_order:
            raise RuntimeError("Test Orders write failed")
        target = payment_confirmation_target(order, now, online=online)
        if order.payment_status == OrdersPaid.PAID:
            return
        confirmed = now if online and target != order.status else order.confirmed_at
        self.repo.db.orders[order.id] = replace(
            order, payment_status=OrdersPaid.PAID, status=target, confirmed_at=confirmed
        )
        if target != order.status:
            self.repo.db.order_histories.append((order.id, order.status, target, now))


class MemoryAuthorization:
    def __init__(self):
        self.grants = set()

    async def has_permission(self, user_id, branch_id, permission):
        return (user_id, branch_id, permission) in self.grants


class TestGateway:
    __test__ = False
    provider_code = "test_gateway"

    def __init__(self, db):
        self.db = db
        self.calls = []
        self.operations = {}
        self.timeout = False
        self.decline = False
        self.before_return = None
        self.verify_calls = 0

    async def create_payment_attempt(self, request):
        assert not self.db.mutex.locked(), (
            "Provider called while transaction holds a lock"
        )
        self.calls.append(request)
        if self.timeout:
            raise TimeoutError("private provider error")
        result = self.operations.setdefault(
            request.provider_idempotency_key,
            GatewayAttemptResult(
                provider_code=self.provider_code,
                provider_reference="ref_" + str(request.attempt_id),
                status=AttemptStatus.FAILED
                if self.decline
                else AttemptStatus.PROCESSING,
                client_action=None
                if self.decline
                else ClientAction(
                    kind="REDIRECT", value="https://checkout.example.test/pay"
                ),
            ),
        )
        if self.before_return:
            await self.before_return()
        return result

    async def verify_and_parse_webhook(self, provider, body, headers):
        self.verify_calls += 1
        signature = headers.get("x-test-signature", "")
        expected = hmac.new(TEST_SECRET, body, hashlib.sha256).hexdigest()
        if provider != self.provider_code or not hmac.compare_digest(
            signature, expected
        ):
            raise PaymentWebhookAuthenticationError()
        try:
            data = json.loads(body)
            return VerifiedPaymentEvent(
                provider_code=provider,
                provider_event_id=data["event"],
                provider_reference=data["reference"],
                result=VerifiedResult(data["result"]),
                amount=Decimal(data["amount"]),
                currency_code=data["currency"],
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
                event_type="test.payment",
            )
        except (ValueError, TypeError, KeyError):
            raise PaymentEventInvalidError() from None


def signed_event(
    attempt,
    *,
    event="evt_1",
    result="SUCCEEDED",
    amount="32.50",
    currency="PEN",
    reference=None,
    occurred_at=NOW,
):
    body = json.dumps(
        {
            "event": event,
            "reference": reference or attempt.provider_reference,
            "result": result,
            "amount": amount,
            "currency": currency,
            "occurred_at": occurred_at.isoformat(),
        },
        sort_keys=True,
    ).encode()
    return body, {
        "x-test-signature": hmac.new(TEST_SECRET, body, hashlib.sha256).hexdigest()
    }


@dataclass
class PaymentSetup:
    db: MemoryDatabase
    repo: MemoryPaymentRepository
    orders: MemoryOrders
    authz: MemoryAuthorization
    gateway: TestGateway
    service: PaymentService
    customer: Principal
    guest: Principal
    foreign: Principal
    admin: Principal
    kitchen: Principal
    order: OrderPaymentContext


def payment_setup():
    db = MemoryDatabase()
    repo = MemoryPaymentRepository(db)
    orders = MemoryOrders(repo)
    authz = MemoryAuthorization()
    gateway = TestGateway(db)
    customer = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    guest = Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())
    foreign = Principal(
        principal_type=PrincipalType.REGISTERED, user_id=uuid4(), customer_id=uuid4()
    )
    admin = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    kitchen = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    order = OrderPaymentContext(
        id=uuid4(),
        customer_id=customer.customer_id,
        branch_id=uuid4(),
        mode=OrderMode.LOCAL,
        status=OrderStatus.PENDING_PAYMENT,
        payment_method_type=PaymentMethodType.ONLINE,
        payment_status=OrdersPaid.PENDING,
        total=Decimal("32.50"),
        confirmed_at=None,
    )
    db.orders[order.id] = order
    authz.grants.add((admin.user_id, order.branch_id, "PAYMENT_CASH_MANAGE"))
    return PaymentSetup(
        db,
        repo,
        orders,
        authz,
        gateway,
        PaymentService(repo, orders, authz, gateway, lambda: NOW),
        customer,
        guest,
        foreign,
        admin,
        kitchen,
        order,
    )


def cash_order(setup, *, status=OrderStatus.PENDING_CASH_CONFIRMATION):
    setup.order = replace(
        setup.order,
        mode=OrderMode.LOCAL,
        status=status,
        payment_method_type=PaymentMethodType.CASH,
        confirmed_at=None
        if status == OrderStatus.PENDING_CASH_CONFIRMATION
        else NOW - timedelta(minutes=5),
    )
    setup.db.orders[setup.order.id] = setup.order
    return setup.order


def change_order(setup, **changes):
    setup.order = replace(setup.db.orders[setup.order.id], **changes)
    setup.db.orders[setup.order.id] = setup.order
    return setup.order


async def initiated(setup, key="key-1"):
    return await setup.service.initiate_online(setup.customer, setup.order.id, key)


async def send_event(setup, attempt, **kwargs):
    body, headers = signed_event(attempt, **kwargs)
    await setup.service.webhook(setup.gateway.provider_code, body, headers)
