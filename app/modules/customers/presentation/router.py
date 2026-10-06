from uuid import UUID

from fastapi import APIRouter, Response, status

from app.modules.customers.application.dtos import (
    Address,
    AddressCreate,
    AddressUpdate,
    ProfileUpdate,
)
from app.modules.customers.presentation.dependencies import (
    CurrentPrincipal,
    CustomerServiceDependency,
)
from app.modules.customers.presentation.schemas import (
    AddressCreateRequest,
    AddressResponse,
    AddressUpdateRequest,
    CustomerProfileResponse,
    ProfileUpdateRequest,
)
from app.presentation.errors import ErrorResponse

router = APIRouter(prefix="/customers", tags=["customers"])
COMMON_ERRORS = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.get(
    "/me",
    response_model=CustomerProfileResponse,
    responses=COMMON_ERRORS,
)
async def get_profile(
    principal: CurrentPrincipal, service: CustomerServiceDependency
) -> CustomerProfileResponse:
    profile = await service.get_profile(principal)
    return CustomerProfileResponse.model_validate(profile)


@router.patch(
    "/me",
    response_model=CustomerProfileResponse,
    responses={
        **COMMON_ERRORS,
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def update_profile(
    payload: ProfileUpdateRequest,
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
) -> CustomerProfileResponse:
    profile = await service.update_profile(
        principal,
        ProfileUpdate(
            provided_fields=frozenset(payload.model_fields_set),
            first_name=payload.first_name,
            last_name=payload.last_name,
            email=str(payload.email) if payload.email is not None else None,
            full_name=payload.full_name,
        ),
    )
    return CustomerProfileResponse.model_validate(profile)


@router.get(
    "/me/addresses",
    response_model=list[AddressResponse],
    responses=COMMON_ERRORS,
)
async def list_addresses(
    principal: CurrentPrincipal, service: CustomerServiceDependency
) -> list[AddressResponse]:
    addresses = await service.list_addresses(principal)
    return [_address_response(address) for address in addresses]


@router.post(
    "/me/addresses",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
    responses=COMMON_ERRORS,
)
async def create_address(
    payload: AddressCreateRequest,
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
) -> AddressResponse:
    address = await service.create_address(
        principal,
        AddressCreate(**payload.model_dump()),
    )
    return _address_response(address)


@router.patch(
    "/me/addresses/{address_id}",
    response_model=AddressResponse,
    responses={**COMMON_ERRORS, 400: {"model": ErrorResponse}},
)
async def update_address(
    address_id: UUID,
    payload: AddressUpdateRequest,
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
) -> AddressResponse:
    values = payload.model_dump()
    address = await service.update_address(
        principal,
        address_id,
        AddressUpdate(
            provided_fields=frozenset(payload.model_fields_set),
            **values,
        ),
    )
    return _address_response(address)


@router.delete(
    "/me/addresses/{address_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=COMMON_ERRORS,
)
async def delete_address(
    address_id: UUID,
    principal: CurrentPrincipal,
    service: CustomerServiceDependency,
) -> Response:
    await service.delete_address(principal, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _address_response(address: Address) -> AddressResponse:
    return AddressResponse.model_validate(address)
