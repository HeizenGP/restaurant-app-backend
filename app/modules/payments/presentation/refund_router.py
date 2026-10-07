from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Header, Path, Query, Request

from app.modules.auth.presentation.dependencies import CurrentRegisteredUser
from app.modules.payments.application.refund_services import MAX_REFUND_WEBHOOK_BYTES
from app.modules.payments.presentation.dependencies import CurrentCustomer
from app.modules.payments.presentation.refund_dependencies import (
    RefundServiceDependency,
)
from app.modules.payments.presentation.refund_schemas import (
    EmptyRequest,
    RefundAdminResponse,
    RefundDetailResponse,
    RefundKey,
    RefundListQuery,
    RefundProcessingResponse,
    RefundResponse,
    RefundWebhookAcknowledgement,
)
from app.presentation.errors import ErrorResponse
from app.shared.application.exceptions import RequestDataError

responses = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/payments", tags=["refunds"], responses=responses)
admin_router = APIRouter(
    prefix="/admin/refunds/branches/{branch_id}",
    tags=["admin refunds"],
    responses=responses,
)
EmptyQuery = Annotated[EmptyRequest, Query()]
EmptyBody = Annotated[EmptyRequest | None, Body()]
Key = Annotated[RefundKey, Header(alias="Idempotency-Key")]


@router.get("/orders/{order_id}/refund", response_model=RefundResponse)
async def get_owned(
    order_id: UUID,
    principal: CurrentCustomer,
    service: RefundServiceDependency,
    query: EmptyQuery,
):
    return await service.get_owned(principal, order_id)


@admin_router.get("", response_model=list[RefundAdminResponse])
async def list_refunds(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: RefundServiceDependency,
    query: Annotated[RefundListQuery, Query()],
):
    return await service.list_branch(
        principal, branch_id, query.status, query.method_type, query.limit, query.offset
    )


@admin_router.get("/{refund_id}", response_model=RefundDetailResponse)
async def detail(
    branch_id: UUID,
    refund_id: UUID,
    principal: CurrentRegisteredUser,
    service: RefundServiceDependency,
    query: EmptyQuery,
):
    return await service.detail(principal, branch_id, refund_id)


@admin_router.post("/{refund_id}/cash/confirm", response_model=RefundResponse)
async def cash_confirm(
    branch_id: UUID,
    refund_id: UUID,
    principal: CurrentRegisteredUser,
    service: RefundServiceDependency,
    query: EmptyQuery,
    body: EmptyBody = None,
):
    return await service.confirm_cash(principal, branch_id, refund_id)


@admin_router.post(
    "/{refund_id}/online/process", response_model=RefundProcessingResponse
)
async def online_process(
    branch_id: UUID,
    refund_id: UUID,
    principal: CurrentRegisteredUser,
    service: RefundServiceDependency,
    query: EmptyQuery,
    idempotency_key: Key,
    body: EmptyBody = None,
):
    return await service.process_online(
        principal, branch_id, refund_id, idempotency_key
    )


@router.post(
    "/refund-webhooks/{provider_code}",
    response_model=RefundWebhookAcknowledgement,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                    "description": (
                        "Opaque provider bytes; signature verification by "
                        "configured refund adapter is mandatory."
                    ),
                }
            },
        }
    },
)
async def refund_webhook(
    request: Request,
    provider_code: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_-]{0,31}$")],
    service: RefundServiceDependency,
    query: EmptyQuery,
):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REFUND_WEBHOOK_BYTES:
            raise RequestDataError("Refund webhook payload is too large")
        raw.extend(chunk)
    await service.webhook(provider_code, bytes(raw), request.headers)
    return RefundWebhookAcknowledgement()
