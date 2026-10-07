from collections.abc import Callable
from datetime import datetime

from app.modules.auth.domain.models import PrincipalType
from app.modules.notifications.application.errors import (
    DeviceNotFoundError,
    NotificationNotFoundError,
    RealtimePermissionError,
)
from app.modules.notifications.domain.models import (
    NotificationRuleError,
    cursor,
    provider_code,
    push_token,
)
from app.shared.application.exceptions import ForbiddenError, RequestDataError
from app.shared.domain.time import utc_now


def limit_value(value, maximum=100):
    if type(value) is not int or not 1 <= value <= maximum:
        raise RequestDataError("Invalid notification limit")


def cursor_value(value):
    try:
        return cursor(value)
    except NotificationRuleError:
        raise RequestDataError("Invalid notification cursor") from None


class NotificationService:
    def __init__(
        self,
        repository,
        authorization,
        registry,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.repo, self.authorization, self.registry, self.clock = (
            repository,
            authorization,
            registry,
            clock,
        )

    @staticmethod
    def customer(principal):
        if principal.customer_id is None:
            raise ForbiddenError("Customer identity required")
        return principal.customer_id

    async def authorize(self, principal, branch, permission="ORDER_REALTIME_VIEW"):
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
            or not await self.authorization.has_permission(
                principal.user_id, branch, permission
            )
        ):
            raise RealtimePermissionError()

    async def _transaction(self, work):
        try:
            result = await work()
            await self.repo.commit()
            return result
        except Exception:
            await self.repo.rollback()
            raise

    async def list_notifications(self, principal, before=None, limit=50):
        limit_value(limit)
        if before is not None:
            cursor_value(before)
        return await self.repo.list_owned(self.customer(principal), before, limit)

    async def unread_count(self, principal):
        return await self.repo.unread_count(self.customer(principal))

    async def mark_read(self, principal, notification):
        async def work():
            value = await self.repo.mark_read(
                self.customer(principal), notification, self.clock()
            )
            if value is None:
                raise NotificationNotFoundError()
            return value

        return await self._transaction(work)

    async def mark_all_read(self, principal):
        return await self._transaction(
            lambda: self.repo.mark_all_read(self.customer(principal), self.clock())
        )

    async def register_device(self, principal, installation, platform, provider, token):
        try:
            provider_code(provider)
            push_token(token)
        except NotificationRuleError:
            raise RequestDataError("Invalid device registration") from None
        customer = self.customer(principal)
        self.registry.resolve(
            provider
        )  # Unconfigured before writes, no fictitious support.
        return await self._transaction(
            lambda: self.repo.register_device(
                customer, installation, platform, provider, token, self.clock()
            )
        )

    async def unregister_device(self, principal, installation):
        async def work():
            if not await self.repo.unregister_device(
                self.customer(principal), installation, self.clock()
            ):
                raise DeviceNotFoundError()

        await self._transaction(work)

    async def get_admin_snapshot(
        self, principal, branch, status=None, after_number=0, limit=100
    ):
        limit_value(limit, 200)
        cursor_value(after_number)
        await self.authorize(principal, branch)
        return await self.repo.admin_snapshot(branch, status, after_number, limit)

    async def list_realtime_events(self, principal, branch, after=0, limit=100):
        limit_value(limit, 200)
        cursor_value(after)
        await self.authorize(principal, branch)
        return await self.repo.events(branch, after, limit)

    async def release(self):
        await self.repo.rollback()
