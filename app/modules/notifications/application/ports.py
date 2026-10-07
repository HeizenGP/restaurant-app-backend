from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.notifications.application.dtos import (
    AdminSnapshot,
    NotificationPage,
    PushClaim,
    PushMessage,
    PushResult,
    StreamBatch,
    StreamScope,
)
from app.modules.notifications.domain.models import (
    DevicePlatform,
    Notification,
    NotificationDevice,
    PushDeliveryStatus,
    RealtimeOrderEvent,
)
from app.modules.orders.domain.models import OrderStatus


class NotificationRepository(Protocol):
    async def list_owned(
        self, customer: UUID, before: int | None, limit: int
    ) -> NotificationPage: ...
    async def unread_count(self, customer: UUID) -> int: ...
    async def mark_read(
        self, customer: UUID, notification: UUID, now: datetime
    ) -> Notification | None: ...
    async def mark_all_read(self, customer: UUID, now: datetime) -> int: ...
    async def register_device(
        self,
        customer: UUID,
        installation: UUID,
        platform: DevicePlatform,
        provider: str,
        token: str,
        now: datetime,
    ) -> NotificationDevice: ...
    async def unregister_device(
        self, customer: UUID, installation: UUID, now: datetime
    ) -> bool: ...
    async def admin_snapshot(
        self, branch: UUID, status: OrderStatus | None, after_number: int, limit: int
    ) -> AdminSnapshot: ...
    async def events(
        self, branch: UUID, after: int, limit: int, until: int | None = None
    ) -> list[RealtimeOrderEvent]: ...
    async def high_watermark(
        self, *, customer: UUID | None = None, branch: UUID | None = None
    ) -> int: ...
    async def stream_notifications(
        self, customer: UUID, after: int, until: int, limit: int
    ) -> list[Notification]: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class NotificationAuthorization(Protocol):
    async def has_permission(
        self, user: UUID, branch: UUID, permission: str
    ) -> bool: ...


class PushGateway(Protocol):
    provider_code: str

    async def send(self, message: PushMessage) -> PushResult: ...


class PushGatewayRegistry(Protocol):
    def provider_codes(self) -> tuple[str, ...]: ...
    def resolve(self, provider: str) -> PushGateway: ...


class PushRepository(Protocol):
    async def claim(
        self, providers: Sequence[str], now: datetime, limit: int
    ) -> list[PushClaim]: ...
    async def can_send(self, claim: PushClaim, now: datetime) -> bool: ...
    async def complete(
        self, claim: PushClaim, result: PushResult, now: datetime
    ) -> PushDeliveryStatus | None: ...


class StreamReader(Protocol):
    async def read(
        self, scope: StreamScope, after: int | None, limit: int, *, revalidate: bool
    ) -> StreamBatch: ...
