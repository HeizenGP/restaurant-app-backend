import json

from fastapi.responses import StreamingResponse

from app.modules.notifications.application.services import cursor_value
from app.modules.notifications.domain.models import Notification, RealtimeOrderEvent
from app.modules.notifications.presentation.schemas import (
    NotificationResponse,
    RealtimeEventResponse,
)
from app.shared.application.exceptions import RequestDataError


def resume_cursor(after_id, last_event_id):
    if after_id is not None:
        return cursor_value(after_id)  # Explicit query cursor wins over the header.
    if last_event_id is None:
        return None
    if not last_event_id.isascii() or not last_event_id.isdecimal():
        raise RequestDataError("Invalid Last-Event-ID")
    if len(last_event_id) > 19:
        raise RequestDataError("Invalid Last-Event-ID")
    return cursor_value(int(last_event_id))


def encode_frame(frame):
    if frame.comment is not None:
        # All comments are constants from the stream service, never raw exceptions.
        return ": " + frame.comment.replace("\n", " ").replace("\r", " ") + "\n\n"
    value = frame.data
    if isinstance(value, Notification):
        value = NotificationResponse.model_validate(value).model_dump(mode="json")
    elif isinstance(value, RealtimeOrderEvent):
        value = RealtimeEventResponse.model_validate(value).model_dump(mode="json")
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return f"id: {frame.id}\nevent: {frame.event}\ndata: {data}\n\n"


async def stream_response(request, scope, after, service, streams):
    # Auth and this repository share the request session. Close its read transaction
    # before opening a long-lived response; each poll uses a separate short session.
    await service.release()
    prepared = await streams.prepare(scope, after)

    async def frames():
        async for frame in streams.stream(scope, prepared, request.is_disconnected):
            yield encode_frame(frame)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
