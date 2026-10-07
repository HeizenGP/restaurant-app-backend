from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from app.modules.payments.application.refund_dtos import (
    RefundAttemptLocator,
    RefundAttemptRequest,
    RefundAttemptResult,
    RefundView,
    VerifiedRefundEvent,
)
from app.modules.payments.domain.models import PaymentAttempt
from app.modules.payments.domain.refunds import (
    Refund,
    RefundAttempt,
    RefundProviderEvent,
    RefundStatus,
    RefundStatusHistory,
)


class OnlineRefundGateway(Protocol):
    @property
    def provider_code(self) -> str: ...
    async def refund(self, request: RefundAttemptRequest) -> RefundAttemptResult: ...
    async def verify_and_parse_webhook(
        self, provider_code: str, raw_body: bytes, headers: Mapping[str, str]
    ) -> VerifiedRefundEvent: ...


class RefundRegistrationRepository(Protocol):
    async def refund_for_order(
        self, order_id: UUID, *, lock: bool
    ) -> Refund | None: ...
    async def insert_refund(self, refund: Refund) -> None: ...
    async def append_history(self, history: RefundStatusHistory) -> None: ...


class RefundRepository(RefundRegistrationRepository, Protocol):
    async def owned(self, customer_id: UUID, order_id: UUID) -> Refund | None: ...
    async def scoped(
        self, branch_id: UUID, refund_id: UUID, *, lock: bool
    ) -> Refund | None: ...
    async def lock_refund(self, refund_id: UUID) -> Refund | None: ...
    async def list_branch(
        self,
        branch_id: UUID,
        status: RefundStatus | None,
        method,
        limit: int,
        offset: int,
    ) -> list[Refund]: ...
    async def view(self, refund: Refund) -> RefundView: ...
    async def save_refund(self, original: Refund, updated: Refund) -> Refund: ...
    async def successful_capture(self, payment_id: UUID) -> PaymentAttempt | None: ...
    async def insert_attempt(self, attempt: RefundAttempt) -> None: ...
    async def save_attempt(
        self, original: RefundAttempt, updated: RefundAttempt
    ) -> RefundAttempt: ...
    async def attempt_by_key(
        self, refund_id: UUID, key: str
    ) -> RefundAttempt | None: ...
    async def active_attempt(self, refund_id: UUID) -> RefundAttempt | None: ...
    async def attempt_by_id(
        self, refund_id: UUID, attempt_id: UUID, *, lock: bool
    ) -> RefundAttempt | None: ...
    async def attempt_locator(
        self, provider: str, reference: str
    ) -> RefundAttemptLocator | None: ...
    async def get_or_insert_event(
        self, event: RefundProviderEvent
    ) -> RefundProviderEvent: ...
    async def save_event(
        self, original: RefundProviderEvent, updated: RefundProviderEvent
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class RefundAuthorization(Protocol):
    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission: str
    ) -> bool: ...
