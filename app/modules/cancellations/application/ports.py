from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.cancellations.domain.models import (
    CancellationRequest,
    OrderCancellation,
    RequestStatus,
)
from app.modules.orders.domain.cancellations import OrderCancellationContext
from app.modules.payments.domain.refunds import Refund


class CancellationOrdersGateway(Protocol):
    async def owned(
        self, customer_id: UUID, order_id: UUID, *, lock: bool
    ) -> OrderCancellationContext | None: ...
    async def scoped(
        self, branch_id: UUID, order_id: UUID, *, lock: bool
    ) -> OrderCancellationContext | None: ...
    async def cancel(
        self, order: OrderCancellationContext, actor: UUID, now: datetime, reason: str
    ) -> None: ...


class CancellationAuthorization(Protocol):
    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission: str
    ) -> bool: ...


class RefundRegistrationGateway(Protocol):
    async def register_if_paid(
        self, order: OrderCancellationContext, now: datetime
    ) -> Refund | None: ...
    async def for_order(self, order_id: UUID) -> Refund | None: ...


class CancellationFulfillmentGateway(Protocol):
    async def close_assignment(
        self, order_id: UUID, actor: UUID, now: datetime
    ) -> None: ...


class CancellationRepository(Protocol):
    async def pending_request(self, order_id: UUID) -> CancellationRequest | None: ...
    async def request(
        self, branch_id: UUID, request_id: UUID, *, lock: bool
    ) -> CancellationRequest | None: ...
    async def insert_request(self, request: CancellationRequest) -> None: ...
    async def save_request(
        self, original: CancellationRequest, updated: CancellationRequest
    ) -> CancellationRequest: ...
    async def list_owned(
        self, customer_id: UUID, order_id: UUID, limit: int, offset: int
    ) -> list[CancellationRequest]: ...
    async def list_branch(
        self, branch_id: UUID, status: RequestStatus | None, limit: int, offset: int
    ) -> list[CancellationRequest]: ...
    async def cancellation(self, order_id: UUID) -> OrderCancellation | None: ...
    async def insert_cancellation(self, cancellation: OrderCancellation) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
