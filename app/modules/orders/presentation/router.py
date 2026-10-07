from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Header, Query, Response, status

from app.modules.auth.presentation.dependencies import CurrentPrincipal
from app.modules.orders.application.dtos import OrderCreate
from app.modules.orders.domain.models import OrderMode
from app.modules.orders.presentation.dependencies import (
    CurrentCustomer,
    OrderServiceDependency,
    OrderSettingsServiceDependency,
)
from app.modules.orders.presentation.schemas import (
    DeliveryCreateRequest,
    EmptyRequest,
    LocalCreateRequest,
    OrderCreateRequest,
    OrderResponse,
    PaginationRequest,
    PickupCreateRequest,
    SettingsPatchRequest,
    SettingsResponse,
    TableCreateRequest,
    TablePatchRequest,
    TableResponse,
    ZoneCreateRequest,
    ZonePatchRequest,
    ZoneResponse,
)
from app.presentation.errors import ErrorResponse

responses = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/orders", tags=["orders"], responses=responses)
admin_router = APIRouter(
    prefix="/admin/orders", tags=["admin orders"], responses=responses
)
EmptyQuery = Annotated[EmptyRequest, Query()]
Pagination = Annotated[PaginationRequest, Query()]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: Annotated[OrderCreateRequest, Body(discriminator="mode")],
    principal: CurrentCustomer,
    service: OrderServiceDependency,
    idempotency_key: IdempotencyKey,
    query: EmptyQuery,
) -> OrderResponse:
    if isinstance(body, LocalCreateRequest):
        command = OrderCreate(
            mode=OrderMode.LOCAL,
            table_qr_token=body.table_qr_token,
            payment_method=body.payment_method,
        )
    elif isinstance(body, PickupCreateRequest):
        command = OrderCreate(
            mode=OrderMode.PICKUP, requested_pickup_at=body.requested_pickup_at
        )
    elif isinstance(body, DeliveryCreateRequest):
        command = OrderCreate(mode=OrderMode.DELIVERY, address_id=body.address_id)
    return OrderResponse.model_validate(
        await service.create(principal, idempotency_key, command)
    )


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    principal: CurrentCustomer,
    service: OrderServiceDependency,
    query: Pagination,
) -> list[OrderResponse]:
    return [
        OrderResponse.model_validate(order)
        for order in await service.list(principal, query.limit, query.offset)
    ]


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    principal: CurrentCustomer,
    service: OrderServiceDependency,
    query: EmptyQuery,
) -> OrderResponse:
    return OrderResponse.model_validate(await service.get(principal, order_id))


@admin_router.post("/{order_id}/confirm-cash-release", response_model=OrderResponse)
async def confirm_cash_release(
    order_id: UUID,
    principal: CurrentPrincipal,
    service: OrderServiceDependency,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> OrderResponse:
    return OrderResponse.model_validate(
        await service.confirm_cash_release(principal, order_id)
    )


@admin_router.get("/branches/{branch_id}/settings", response_model=SettingsResponse)
async def get_settings(
    branch_id: UUID,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> SettingsResponse:
    return SettingsResponse.model_validate(
        await service.get_settings(principal, branch_id)
    )


@admin_router.patch("/branches/{branch_id}/settings", response_model=SettingsResponse)
async def update_settings(
    branch_id: UUID,
    body: SettingsPatchRequest,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> SettingsResponse:
    return SettingsResponse.model_validate(
        await service.update_settings(
            principal, branch_id, body.model_dump(exclude_unset=True)
        )
    )


@admin_router.get("/branches/{branch_id}/tables", response_model=list[TableResponse])
async def list_tables(
    branch_id: UUID,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> list[TableResponse]:
    return [
        TableResponse.model_validate(table)
        for table in await service.list_tables(principal, branch_id)
    ]


@admin_router.post(
    "/branches/{branch_id}/tables",
    response_model=TableResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_table(
    branch_id: UUID,
    body: TableCreateRequest,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> TableResponse:
    return TableResponse.model_validate(
        await service.create_table(principal, branch_id, body.label)
    )


@admin_router.patch(
    "/branches/{branch_id}/tables/{table_id}", response_model=TableResponse
)
async def update_table(
    branch_id: UUID,
    table_id: UUID,
    body: TablePatchRequest,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> TableResponse:
    return TableResponse.model_validate(
        await service.update_table(
            principal, branch_id, table_id, body.model_dump(exclude_unset=True)
        )
    )


@admin_router.delete(
    "/branches/{branch_id}/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def deactivate_table(
    branch_id: UUID,
    table_id: UUID,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> Response:
    await service.deactivate_table(principal, branch_id, table_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get(
    "/branches/{branch_id}/delivery-zones", response_model=list[ZoneResponse]
)
async def list_zones(
    branch_id: UUID,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> list[ZoneResponse]:
    return [
        ZoneResponse.model_validate(zone)
        for zone in await service.list_zones(principal, branch_id)
    ]


@admin_router.post(
    "/branches/{branch_id}/delivery-zones",
    response_model=ZoneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_zone(
    branch_id: UUID,
    body: ZoneCreateRequest,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> ZoneResponse:
    return ZoneResponse.model_validate(
        await service.create_zone(principal, branch_id, body.model_dump())
    )


@admin_router.patch(
    "/branches/{branch_id}/delivery-zones/{zone_id}", response_model=ZoneResponse
)
async def update_zone(
    branch_id: UUID,
    zone_id: UUID,
    body: ZonePatchRequest,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
) -> ZoneResponse:
    return ZoneResponse.model_validate(
        await service.update_zone(
            principal, branch_id, zone_id, body.model_dump(exclude_unset=True)
        )
    )


@admin_router.delete(
    "/branches/{branch_id}/delivery-zones/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def deactivate_zone(
    branch_id: UUID,
    zone_id: UUID,
    principal: CurrentPrincipal,
    service: OrderSettingsServiceDependency,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> Response:
    await service.deactivate_zone(principal, branch_id, zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
