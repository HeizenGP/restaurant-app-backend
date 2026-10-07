import asyncio
import time

from app.modules.notifications.application.dtos import StreamFrame
from app.modules.notifications.application.services import cursor_value
from app.shared.application.exceptions import ApplicationError, RequestDataError
from app.shared.domain.time import utc_now

SSE_BATCH_SIZE = 100
SSE_POLL_SECONDS = 1.0
SSE_HEARTBEAT_SECONDS = 15.0
SSE_REVALIDATE_SECONDS = 15.0
SSE_MAX_LIFETIME_SECONDS = 300.0


class RealtimeStreamService:
    def __init__(
        self, reader, *, clock=utc_now, monotonic=time.monotonic, sleep=asyncio.sleep
    ):
        self.reader, self.clock, self.monotonic, self.sleep = (
            reader,
            clock,
            monotonic,
            sleep,
        )

    async def prepare(self, scope, after=None):
        if after is not None:
            cursor_value(after)
        initial = await self.reader.read(scope, after, SSE_BATCH_SIZE, revalidate=True)
        if after is not None and after > initial.latest_id:
            raise RequestDataError("Cursor is ahead of this stream")
        return after if after is not None else initial.latest_id, initial, after is None

    async def stream(self, scope, prepared, is_disconnected):
        after, initial, resync_required = prepared
        start = self.monotonic()
        heartbeat_at = validated_at = start
        expires = initial.expires_at
        yield StreamFrame(
            event="ready",
            id=after,
            data={
                "latest_event_id": initial.latest_id,
                "start_after_id": after,
                "resync_required": resync_required,
            },
        )
        batch = initial if initial.items else None
        try:
            while self.monotonic() - start < SSE_MAX_LIFETIME_SECONDS:
                if await is_disconnected() or (
                    expires is not None and self.clock() >= expires
                ):
                    return
                if batch is None:
                    revalidate = (
                        self.monotonic() - validated_at >= SSE_REVALIDATE_SECONDS
                    )
                    batch = await self.reader.read(
                        scope, after, SSE_BATCH_SIZE, revalidate=revalidate
                    )
                    if revalidate:
                        validated_at = self.monotonic()
                        expires = batch.expires_at
                    if expires is not None and self.clock() >= expires:
                        return
                for item in batch.items:
                    if self.monotonic() - validated_at >= SSE_REVALIDATE_SECONDS:
                        # A slow consumer may suspend between items of one batch.
                        # Recheck authorization without consuming its pending rows.
                        validation = await self.reader.read(
                            scope, None, 1, revalidate=True
                        )
                        validated_at = self.monotonic()
                        expires = validation.expires_at
                    if (
                        await is_disconnected()
                        or self.monotonic() - start >= SSE_MAX_LIFETIME_SECONDS
                        or (expires is not None and self.clock() >= expires)
                    ):
                        return
                    item_id = item.sequence_id if scope.branch_id is None else item.id
                    yield StreamFrame(
                        event="notification.created"
                        if scope.branch_id is None
                        else {
                            "ORDER_CREATED": "order.created",
                            "ORDER_CHANGED": "order.changed",
                            "DELIVERY_DELAYED": "delivery.delayed",
                        }[item.event_type.value],
                        id=item_id,
                        data=item,
                    )
                    after = item_id
                full = len(batch.items) == SSE_BATCH_SIZE
                batch = None
                if self.monotonic() - heartbeat_at >= SSE_HEARTBEAT_SECONDS:
                    yield StreamFrame(comment="keep-alive")
                    heartbeat_at = self.monotonic()
                if not full:
                    await self.sleep(SSE_POLL_SECONDS)
        except ApplicationError:
            # HTTP headers already sent: no raw provider/DB/auth error in SSE.
            yield StreamFrame(comment="stream closed; reconnect with last event id")
            return
