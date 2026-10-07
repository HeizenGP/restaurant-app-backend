from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query

from app.modules.auth.presentation.dependencies import CurrentPrincipal
from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.presentation.dependencies import KitchenServiceDependency
from app.modules.kitchen.presentation.schemas import (
    EmptyRequest,
    KitchenOrderDetailResponse,
    KitchenQueueResponse,
    QueueRequest,
)
from app.modules.orders.domain.models import OrderStatus
from app.presentation.errors import ErrorResponse

router = APIRouter(
    prefix="/kitchen/branches/{branch_id}",
    tags=["kitchen"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)
EmptyQuery = Annotated[EmptyRequest, Query()]
QueueQuery = Annotated[QueueRequest, Query()]


@router.get(
    "/queue",
    response_model=KitchenQueueResponse,
    summary="Read the confirmed operational queue (KITCHEN_VIEW)",
    description="Read-only, branch-scoped polling. No scheduled-order activation. "
    "Pages prioritize waiting, preparing, then ready; oldest status entry first.",
)
async def get_queue(
    branch_id: UUID,
    principal: CurrentPrincipal,
    service: KitchenServiceDependency,
    query: QueueQuery,
) -> KitchenQueueResponse:
    filters = KitchenQueueQuery(
        limit=query.limit,
        offset=query.offset,
        mode=query.mode,
        status=OrderStatus(query.status) if query.status is not None else None,
    )
    return KitchenQueueResponse.model_validate(
        await service.get_queue(principal, branch_id, filters)
    )


@router.get(
    "/orders/{order_id}",
    response_model=KitchenOrderDetailResponse,
    summary="Read an active Kitchen order and history (KITCHEN_VIEW)",
    description="Only operational orders from the authorized branch. "
    "Excluded or cross-branch orders return 404. No customer or financial data.",
)
async def get_order(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentPrincipal,
    service: KitchenServiceDependency,
    query: EmptyQuery,
) -> KitchenOrderDetailResponse:
    return KitchenOrderDetailResponse.model_validate(
        await service.get_kitchen_order(principal, branch_id, order_id)
    )


@router.post(
    "/orders/{order_id}/start-preparation",
    response_model=KitchenOrderDetailResponse,
    summary="WAITING → PREPARING (KITCHEN_MANAGE)",
    description="Atomic status/history write under an Order lock. "
    "Retry while PREPARING returns 200 without a duplicate history entry. "
    "An incompatible later/earlier state returns 409. Empty body only.",
)
async def start_preparation(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentPrincipal,
    service: KitchenServiceDependency,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> KitchenOrderDetailResponse:
    return KitchenOrderDetailResponse.model_validate(
        await service.start_preparation(principal, branch_id, order_id)
    )


@router.post(
    "/orders/{order_id}/mark-ready",
    response_model=KitchenOrderDetailResponse,
    summary="PREPARING → mode-specific ready (KITCHEN_MANAGE)",
    description="LOCAL/DELIVERY become READY; PICKUP becomes READY_FOR_PICKUP. "
    "Retry at the correct target returns 200 without duplicate history. "
    "No skipped stages, payment changes, cancellation or fulfillment.",
)
async def mark_ready(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentPrincipal,
    service: KitchenServiceDependency,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> KitchenOrderDetailResponse:
    return KitchenOrderDetailResponse.model_validate(
        await service.mark_ready(principal, branch_id, order_id)
    )
