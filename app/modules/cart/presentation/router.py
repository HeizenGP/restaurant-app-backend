from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query, Response, status

from app.modules.cart.application.dtos import AddonSelection, ItemCreate, ItemUpdate
from app.modules.cart.presentation.dependencies import (
    CartServiceDependency,
    CurrentCustomer,
)
from app.modules.cart.presentation.schemas import (
    CartCreateRequest,
    CartItemResponse,
    CartResponse,
    EmptyBodyRequest,
    EmptyQueryRequest,
    ItemCreateRequest,
    ItemPatchRequest,
)
from app.presentation.errors import ErrorResponse

router = APIRouter(
    prefix="/cart",
    tags=["cart"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)
CartQuery = Annotated[EmptyQueryRequest, Query()]


@router.post("", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
async def create_cart(
    body: CartCreateRequest,
    principal: CurrentCustomer,
    service: CartServiceDependency,
    query: CartQuery,
) -> CartResponse:
    return CartResponse.model_validate(
        await service.create_cart(principal, body.branch_id)
    )


@router.get("", response_model=CartResponse)
async def get_cart(
    principal: CurrentCustomer, service: CartServiceDependency, query: CartQuery
) -> CartResponse:
    return CartResponse.model_validate(await service.get_cart(principal))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def abandon_cart(
    principal: CurrentCustomer,
    service: CartServiceDependency,
    query: CartQuery,
    body: Annotated[EmptyBodyRequest | None, Body()] = None,
) -> Response:
    await service.abandon_cart(principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/items", response_model=CartItemResponse, status_code=status.HTTP_201_CREATED
)
async def add_item(
    body: ItemCreateRequest,
    principal: CurrentCustomer,
    service: CartServiceDependency,
    query: CartQuery,
) -> CartItemResponse:
    command = ItemCreate(
        product_id=body.product_id,
        presentation_id=body.presentation_id,
        quantity=body.quantity,
        notes=body.notes,
        addons=tuple(
            AddonSelection(addon.addon_id, tuple(addon.option_ids))
            for addon in body.addons
        ),
    )
    return CartItemResponse.model_validate(await service.add_item(principal, command))


@router.patch("/items/{item_id}", response_model=CartItemResponse)
async def update_item(
    item_id: UUID,
    body: ItemPatchRequest,
    principal: CurrentCustomer,
    service: CartServiceDependency,
    query: CartQuery,
) -> CartItemResponse:
    command = ItemUpdate(
        provided_fields=frozenset(body.model_fields_set),
        quantity=body.quantity,
        presentation_id=body.presentation_id,
        notes=body.notes,
        addons=None
        if body.addons is None
        else tuple(
            AddonSelection(addon.addon_id, tuple(addon.option_ids))
            for addon in body.addons
        ),
    )
    return CartItemResponse.model_validate(
        await service.update_item(principal, item_id, command)
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    principal: CurrentCustomer,
    service: CartServiceDependency,
    query: CartQuery,
    body: Annotated[EmptyBodyRequest | None, Body()] = None,
) -> Response:
    await service.delete_item(principal, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/recalculate", response_model=CartResponse)
async def recalculate_cart(
    principal: CurrentCustomer,
    service: CartServiceDependency,
    query: CartQuery,
    body: Annotated[EmptyBodyRequest | None, Body()] = None,
) -> CartResponse:
    return CartResponse.model_validate(await service.recalculate_cart(principal))
