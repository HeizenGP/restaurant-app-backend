from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import (
    BearerDependency,
    CurrentRegisteredUser,
    get_current_customer,
)
from app.modules.notifications.application.dtos import StreamScope
from app.modules.notifications.presentation.dependencies import (
    NotificationServiceDependency,
    StreamServiceDependency,
)
from app.modules.notifications.presentation.schemas import (
    DeviceRequest,
    DeviceResponse,
    EmptyRequest,
    EventsQuery,
    NotificationListQuery,
    NotificationPageResponse,
    NotificationResponse,
    ReadAllResponse,
    RealtimeEventResponse,
    SnapshotQuery,
    SnapshotResponse,
    StreamQuery,
    UnreadResponse,
)
from app.modules.notifications.presentation.sse import resume_cursor, stream_response
from app.presentation.errors import ErrorResponse

responses = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/notifications", tags=["notifications"], responses=responses)
admin_router = APIRouter(
    prefix="/admin/realtime/branches/{branch_id}/orders",
    tags=["admin realtime"],
    responses=responses,
)
kitchen_router = APIRouter(
    prefix="/kitchen/branches/{branch_id}/orders",
    tags=["kitchen realtime"],
    responses=responses,
)
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]
EmptyQuery = Annotated[EmptyRequest, Query()]
LastEventId = Annotated[str | None, Header(alias="Last-Event-ID")]
sse_response = {200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}}


@router.get("", response_model=NotificationPageResponse)
async def list_owned(
    principal: CurrentCustomer,
    service: NotificationServiceDependency,
    query: Annotated[NotificationListQuery, Query()],
):
    return await service.list_notifications(
        principal, query.before_sequence_id, query.limit
    )


@router.get("/unread-count", response_model=UnreadResponse)
async def unread_count(
    principal: CurrentCustomer,
    service: NotificationServiceDependency,
    query: EmptyQuery,
):
    return {"unread_count": await service.unread_count(principal)}


@router.post("/read-all", response_model=ReadAllResponse)
async def read_all(
    principal: CurrentCustomer,
    service: NotificationServiceDependency,
    query: EmptyQuery,
    body: EmptyRequest | None = None,
):
    return {"marked_count": await service.mark_all_read(principal)}


@router.get("/stream", response_class=StreamingResponse, responses=sse_response)
async def customer_stream(
    request: Request,
    principal: CurrentCustomer,
    credentials: BearerDependency,
    service: NotificationServiceDependency,
    streams: StreamServiceDependency,
    query: Annotated[StreamQuery, Query()],
    last_event_id: LastEventId = None,
):
    scope = StreamScope(principal=principal, credential=credentials.credentials)
    return await stream_response(
        request, scope, resume_cursor(query.after_id, last_event_id), service, streams
    )


@router.put("/devices/{installation_id}", response_model=DeviceResponse)
async def register_device(
    installation_id: UUID,
    body: DeviceRequest,
    principal: CurrentCustomer,
    service: NotificationServiceDependency,
    query: EmptyQuery,
):
    return await service.register_device(
        principal, installation_id, body.platform, body.provider_code, body.push_token
    )


@router.delete("/devices/{installation_id}", status_code=204)
async def unregister_device(
    installation_id: UUID,
    principal: CurrentCustomer,
    service: NotificationServiceDependency,
    query: EmptyQuery,
):
    await service.unregister_device(principal, installation_id)
    return Response(status_code=204)


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def read_one(
    notification_id: UUID,
    principal: CurrentCustomer,
    service: NotificationServiceDependency,
    query: EmptyQuery,
    body: EmptyRequest | None = None,
):
    return await service.mark_read(principal, notification_id)


@admin_router.get("", response_model=SnapshotResponse)
async def snapshot(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: NotificationServiceDependency,
    query: Annotated[SnapshotQuery, Query()],
):
    return await service.get_admin_snapshot(
        principal, branch_id, query.status, query.after_order_number, query.limit
    )


@admin_router.get("/events", response_model=list[RealtimeEventResponse])
async def events(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: NotificationServiceDependency,
    query: Annotated[EventsQuery, Query()],
):
    return await service.list_realtime_events(
        principal, branch_id, query.after_id, query.limit
    )


@admin_router.get("/stream", response_class=StreamingResponse, responses=sse_response)
async def admin_stream(
    branch_id: UUID,
    request: Request,
    principal: CurrentRegisteredUser,
    credentials: BearerDependency,
    service: NotificationServiceDependency,
    streams: StreamServiceDependency,
    query: Annotated[StreamQuery, Query()],
    last_event_id: LastEventId = None,
):
    await service.authorize(principal, branch_id)
    scope = StreamScope(
        principal=principal,
        credential=credentials.credentials,
        branch_id=branch_id,
        permission="ORDER_REALTIME_VIEW",
    )
    return await stream_response(
        request, scope, resume_cursor(query.after_id, last_event_id), service, streams
    )


@kitchen_router.get("/stream", response_class=StreamingResponse, responses=sse_response)
async def kitchen_stream(
    branch_id: UUID,
    request: Request,
    principal: CurrentRegisteredUser,
    credentials: BearerDependency,
    service: NotificationServiceDependency,
    streams: StreamServiceDependency,
    query: Annotated[StreamQuery, Query()],
    last_event_id: LastEventId = None,
):
    await service.authorize(principal, branch_id, "KITCHEN_VIEW")
    scope = StreamScope(
        principal=principal,
        credential=credentials.credentials,
        branch_id=branch_id,
        permission="KITCHEN_VIEW",
    )
    return await stream_response(
        request, scope, resume_cursor(query.after_id, last_event_id), service, streams
    )
