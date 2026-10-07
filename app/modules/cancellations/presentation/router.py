from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    get_current_customer,
)
from app.modules.cancellations.domain.models import ReasonCode, RequestStatus
from app.modules.cancellations.presentation.dependencies import (
    CancellationServiceDependency,
)
from app.modules.cancellations.presentation.schemas import (
    AdminRequestResponse,
    CreateRequest,
    CustomerRequestResponse,
    DirectCancelRequest,
    EmptyRequest,
    OutcomeResponse,
    PaginationRequest,
    RequestListQuery,
    ReviewRequest,
)
from app.presentation.errors import ErrorResponse

responses = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(
    prefix="/orders/{order_id}/cancellation-requests",
    tags=["cancellation requests"],
    responses=responses,
)
admin_router = APIRouter(
    prefix="/admin/cancellations/branches/{branch_id}",
    tags=["admin cancellations"],
    responses=responses,
)
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]
EmptyQuery = Annotated[EmptyRequest, Query()]


@router.post(
    "",
    response_model=CustomerRequestResponse,
    status_code=201,
    responses={200: {"model": CustomerRequestResponse}},
)
async def create_request(
    order_id: UUID,
    body: CreateRequest,
    response: Response,
    principal: CurrentCustomer,
    service: CancellationServiceDependency,
    query: EmptyQuery,
):
    result = await service.create_request(principal, order_id, body.reason)
    response.status_code = 201 if result.created else 200
    return result.request


@router.get("", response_model=list[CustomerRequestResponse])
async def list_owned(
    order_id: UUID,
    principal: CurrentCustomer,
    service: CancellationServiceDependency,
    query: Annotated[PaginationRequest, Query()],
):
    return await service.list_owned(principal, order_id, query.limit, query.offset)


@admin_router.get("/requests", response_model=list[AdminRequestResponse])
async def list_requests(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: CancellationServiceDependency,
    query: Annotated[RequestListQuery, Query()],
):
    return await service.list_branch(
        principal, branch_id, query.status, query.limit, query.offset
    )


@admin_router.post("/requests/{request_id}/approve", response_model=OutcomeResponse)
async def approve(
    branch_id: UUID,
    request_id: UUID,
    body: ReviewRequest,
    principal: CurrentRegisteredUser,
    service: CancellationServiceDependency,
    query: EmptyQuery,
):
    return await service.review(
        principal, branch_id, request_id, RequestStatus.APPROVED, body.evaluation_note
    )


@admin_router.post("/requests/{request_id}/reject", response_model=AdminRequestResponse)
async def reject(
    branch_id: UUID,
    request_id: UUID,
    body: ReviewRequest,
    principal: CurrentRegisteredUser,
    service: CancellationServiceDependency,
    query: EmptyQuery,
):
    return await service.review(
        principal, branch_id, request_id, RequestStatus.REJECTED, body.evaluation_note
    )


@admin_router.post("/orders/{order_id}/cancel", response_model=OutcomeResponse)
async def cancel(
    branch_id: UUID,
    order_id: UUID,
    body: DirectCancelRequest,
    principal: CurrentRegisteredUser,
    service: CancellationServiceDependency,
    query: EmptyQuery,
):
    return await service.cancel_order(
        principal, branch_id, order_id, ReasonCode(body.reason_code), body.reason
    )


@admin_router.get("/orders/{order_id}", response_model=OutcomeResponse)
async def detail(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentRegisteredUser,
    service: CancellationServiceDependency,
    query: EmptyQuery,
):
    return await service.detail(principal, branch_id, order_id)
