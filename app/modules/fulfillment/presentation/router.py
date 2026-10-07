from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query, Response, status

from app.modules.auth.presentation.dependencies import CurrentRegisteredUser
from app.modules.fulfillment.domain.models import DecisionStatus
from app.modules.fulfillment.presentation.dependencies import (
    FulfillmentServiceDependency,
)
from app.modules.fulfillment.presentation.schemas import (
    ApproveRequest,
    AssignmentRequest,
    AssignmentResponse,
    BulkReleaseResponse,
    DeliveryQueueResponse,
    DetectionRequest,
    DetectionResponse,
    EmptyRequest,
    IncidentListRequest,
    IncidentResponse,
    LimitRequest,
    PaginationRequest,
    PickupCompleteRequest,
    PickupRecommendationResponse,
    QueueRequest,
    RejectRequest,
    TransitionResponse,
)
from app.modules.orders.domain.models import OrderStatus
from app.presentation.errors import ErrorResponse

router = APIRouter(
    prefix="/admin/fulfillment/branches/{branch_id}",
    tags=["admin fulfillment"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)
EmptyQuery = Annotated[EmptyRequest, Query()]
OptionalBody = Annotated[EmptyRequest | None, Body()]


@router.get("/pickup/due", response_model=list[PickupRecommendationResponse])
async def pickup_due(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: Annotated[PaginationRequest, Query()],
):
    """Upcoming/due paid pickups; read-only recommendation from current queue."""
    return await service.pickup_due(principal, branch_id, query.limit, query.offset)


@router.post("/pickup/release-due", response_model=BulkReleaseResponse)
async def release_due(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: Annotated[LimitRequest, Query()],
    body: OptionalBody = None,
):
    """Bounded SKIP LOCKED batch; periodic worker belongs to deployment."""
    return await service.release_due_pickups(principal, branch_id, query.limit)


@router.post("/pickup/orders/{order_id}/release", response_model=TransitionResponse)
async def release_pickup(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
    body: OptionalBody = None,
):
    return await service.release_pickup(principal, branch_id, order_id)


@router.post("/pickup/orders/{order_id}/complete", response_model=TransitionResponse)
async def complete_pickup(
    branch_id: UUID,
    order_id: UUID,
    body: PickupCompleteRequest,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
):
    return await service.complete_pickup(
        principal, branch_id, order_id, body.customer_name, body.customer_phone
    )


@router.get("/delivery/queue", response_model=list[DeliveryQueueResponse])
async def delivery_queue(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: Annotated[QueueRequest, Query()],
):
    rows = await service.delivery_queue(
        principal,
        branch_id,
        OrderStatus(query.status) if query.status else None,
        query.limit,
        query.offset,
    )
    return [DeliveryQueueResponse.from_card(card) for card in rows]


@router.put("/delivery/orders/{order_id}/assignment", response_model=AssignmentResponse)
async def assign_delivery(
    branch_id: UUID,
    order_id: UUID,
    body: AssignmentRequest,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
):
    return await service.assign_delivery(
        principal, branch_id, order_id, body.assigned_user_id
    )


@router.delete(
    "/delivery/orders/{order_id}/assignment", status_code=status.HTTP_204_NO_CONTENT
)
async def unassign_delivery(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
    body: OptionalBody = None,
):
    await service.unassign_delivery(principal, branch_id, order_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/delivery/orders/{order_id}/dispatch", response_model=TransitionResponse)
async def dispatch_delivery(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
    body: OptionalBody = None,
):
    return await service.dispatch_delivery(principal, branch_id, order_id)


@router.post("/delivery/orders/{order_id}/complete", response_model=TransitionResponse)
async def complete_delivery(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
    body: OptionalBody = None,
):
    return await service.complete_delivery(principal, branch_id, order_id)


@router.post("/delivery/delays/detect", response_model=DetectionResponse)
async def detect_delays(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: Annotated[DetectionRequest, Query()],
    body: OptionalBody = None,
):
    return await service.detect_delivery_delays(
        principal, branch_id, query.limit, query.after_order_number
    )


@router.get("/delivery/delays", response_model=list[IncidentResponse])
async def list_delays(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: Annotated[IncidentListRequest, Query()],
):
    return await service.list_delays(
        principal, branch_id, query.status, query.limit, query.offset
    )


@router.post("/delivery/delays/{incident_id}/approve", response_model=IncidentResponse)
async def approve_delay(
    branch_id: UUID,
    incident_id: UUID,
    body: ApproveRequest,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
):
    return await service.decide_delay(
        principal,
        branch_id,
        incident_id,
        DecisionStatus.APPROVED,
        body.customer_responsibility,
        body.evaluation_note,
        body.remediation_description,
    )


@router.post("/delivery/delays/{incident_id}/reject", response_model=IncidentResponse)
async def reject_delay(
    branch_id: UUID,
    incident_id: UUID,
    body: RejectRequest,
    principal: CurrentRegisteredUser,
    service: FulfillmentServiceDependency,
    query: EmptyQuery,
):
    return await service.decide_delay(
        principal,
        branch_id,
        incident_id,
        DecisionStatus.REJECTED,
        body.customer_responsibility,
        body.evaluation_note,
    )
