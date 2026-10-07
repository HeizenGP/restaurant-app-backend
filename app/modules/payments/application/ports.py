from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.orders.domain.payments import OrderPaymentContext
from app.modules.payments.application.dtos import (
    AttemptLocator,
    GatewayAttemptRequest,
    GatewayAttemptResult,
    PaymentView,
    VerifiedPaymentEvent,
)
from app.modules.payments.domain.models import (
    Payment,
    PaymentAttempt,
    PaymentStatusHistory,
    ProviderEvent,
)


class OnlinePaymentGateway(Protocol):
    @property
    def provider_code(self) -> str: ...
    async def create_payment_attempt(
        self, request: GatewayAttemptRequest
    ) -> GatewayAttemptResult:
        """Must create/recover ONE provider operation for provider_idempotency_key."""
        ...

    async def verify_and_parse_webhook(
        self, provider_code: str, raw_body: bytes, headers: Mapping[str, str]
    ) -> VerifiedPaymentEvent: ...


class PaymentOrderLifecycle(Protocol):
    async def owned_context(
        self, customer_id: UUID, order_id: UUID, *, lock: bool
    ) -> OrderPaymentContext | None: ...
    async def branch_context(
        self, branch_id: UUID, order_id: UUID, *, lock: bool
    ) -> OrderPaymentContext | None: ...
    async def lock_context(self, order_id: UUID) -> OrderPaymentContext | None: ...
    async def confirm_paid(
        self, order: OrderPaymentContext, now: datetime, *, online: bool
    ) -> None: ...


class PaymentAuthorization(Protocol):
    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission: str
    ) -> bool: ...


class PaymentRepository(Protocol):
    async def get_owned(
        self, customer_id: UUID, order_id: UUID
    ) -> PaymentView | None: ...
    async def payment_for_order(
        self, order_id: UUID, *, lock: bool
    ) -> Payment | None: ...
    async def insert_payment(self, payment: Payment) -> None: ...
    async def save_payment(self, original: Payment, updated: Payment) -> Payment: ...
    async def view(self, payment: Payment) -> PaymentView: ...
    async def insert_attempt(self, attempt: PaymentAttempt) -> None: ...
    async def save_attempt(
        self, original: PaymentAttempt, updated: PaymentAttempt
    ) -> PaymentAttempt: ...
    async def attempt_by_key(
        self, payment_id: UUID, key: str
    ) -> PaymentAttempt | None: ...
    async def active_attempt(self, payment_id: UUID) -> PaymentAttempt | None: ...
    async def attempt_by_id(
        self, payment_id: UUID, attempt_id: UUID, *, lock: bool
    ) -> PaymentAttempt | None: ...
    async def attempt_locator(
        self, provider: str, reference: str
    ) -> AttemptLocator | None: ...
    async def append_history(self, history: PaymentStatusHistory) -> None: ...
    async def get_or_insert_event(self, event: ProviderEvent) -> ProviderEvent: ...
    async def save_event(
        self, original: ProviderEvent, updated: ProviderEvent
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
