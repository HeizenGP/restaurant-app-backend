"""Short local reservations and fenced results, never I/O under a DB lock."""

import asyncio
import math
from dataclasses import replace

from app.modules.notifications.application.dtos import (
    DispatchResult,
    PushMessage,
    PushResult,
)
from app.modules.notifications.application.errors import PushProviderUnavailableError
from app.modules.notifications.application.services import limit_value
from app.modules.notifications.domain.content import content
from app.modules.notifications.domain.models import (
    PUSH_LEASE_SECONDS,
    PushDeliveryStatus,
    PushResultKind,
)
from app.shared.application.exceptions import RequestDataError
from app.shared.domain.time import utc_now


class PushDispatchService:
    def __init__(
        self,
        repository,
        registry,
        *,
        clock=utc_now,
        parallelism=10,
        timeout_seconds=30.0,
    ):
        limit_value(parallelism, 20)
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= PUSH_LEASE_SECONDS / 2
        ):
            raise RequestDataError("Invalid push send timeout")
        self.timeout_seconds = timeout_seconds
        self.repo, self.registry, self.clock, self.parallelism = (
            repository,
            registry,
            clock,
            parallelism,
        )

    async def dispatch_pending_pushes(self, limit=50):
        limit_value(limit, 100)
        providers = self.registry.provider_codes()
        if not providers:
            raise PushProviderUnavailableError()
        for provider in providers:
            self.registry.resolve(provider)
        claims = await self.repo.claim(providers, self.clock(), limit)
        semaphore = asyncio.Semaphore(self.parallelism)

        async def send(claim):
            async with semaphore:
                if not await self.repo.can_send(claim, self.clock()):
                    return None
                n = claim.notification
                wording = content(n.kind, n.order_number_snapshot)
                message = PushMessage(
                    delivery_id=claim.delivery.id,
                    notification_id=n.id,
                    token=claim.device.push_token,
                    title=wording.title,
                    body=wording.body,
                    data={
                        "order_id": str(n.order_id),
                        "order_number": str(n.order_number_snapshot),
                        "kind": n.kind.value,
                        "status": n.order_status.value if n.order_status else "",
                    },
                    provider_idempotency_key="push-delivery:" + str(claim.delivery.id),
                )
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        result = await self.registry.resolve(
                            claim.delivery.provider_code
                        ).send(message)
                    if not isinstance(result, PushResult) or not isinstance(
                        result.kind, PushResultKind
                    ):
                        result = PushResult(kind=PushResultKind.RETRYABLE_FAILURE)
                except (OSError, TimeoutError, PushProviderUnavailableError):
                    result = PushResult(kind=PushResultKind.RETRYABLE_FAILURE)
                # Unexpected adapters fail the invocation, leaving recoverable lease.
                if result.kind != PushResultKind.SENT:
                    result = replace(result, provider_message_id=None)
                return await self.repo.complete(claim, result, self.clock())

        states = await asyncio.gather(*(send(c) for c in claims))
        return DispatchResult(
            claimed=len(claims),
            sent=states.count(PushDeliveryStatus.SENT),
            failed=states.count(PushDeliveryStatus.FAILED),
            pending=states.count(PushDeliveryStatus.PENDING),
            cancelled_or_stale=sum(
                s is None or s == PushDeliveryStatus.CANCELLED for s in states
            ),
        )
