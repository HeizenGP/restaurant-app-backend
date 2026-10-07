from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    SessionDependency,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.customers.application.admin_services import (
    CustomerAdministrationService,
)
from app.modules.customers.infrastructure.persistence.admin_repository import (
    SQLAlchemyCustomerAdministrationRepository,
)
from app.modules.customers.presentation.admin_schemas import (
    AdministrativeCustomerResponse,
    CreateAdministrativeCustomer,
    CustomerSearch,
    UpdateAdministrativeCustomer,
)
from app.presentation.errors import ErrorResponse
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder

router = APIRouter(
    prefix="/admin/branches/{branch_id}/customers",
    tags=["admin customers"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)


def get_customer_administration_service(
    session: SessionDependency,
) -> CustomerAdministrationService:
    return CustomerAdministrationService(
        SQLAlchemyBranchRepository(session),
        SQLAlchemyCustomerAdministrationRepository(session),
        SQLAlchemyAuditRecorder(session),
    )


Service = Annotated[
    CustomerAdministrationService, Depends(get_customer_administration_service)
]


@router.get("", response_model=list[AdministrativeCustomerResponse])
async def list_customers(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
    query: Annotated[CustomerSearch, Query()],
):
    return await service.list(
        principal, branch_id, query.search, query.limit, query.offset
    )


@router.get("/{customer_id}", response_model=AdministrativeCustomerResponse)
async def get_customer(
    branch_id: UUID,
    customer_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.get(principal, branch_id, customer_id)


@router.post("", status_code=201, response_model=AdministrativeCustomerResponse)
async def create_customer(
    branch_id: UUID,
    body: CreateAdministrativeCustomer,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.mutate(principal, branch_id, "CREATE", body.model_dump())


@router.patch("/{customer_id}", response_model=AdministrativeCustomerResponse)
async def update_customer(
    branch_id: UUID,
    customer_id: UUID,
    body: UpdateAdministrativeCustomer,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.mutate(
        principal, branch_id, "UPDATE", body.model_dump(exclude_unset=True), customer_id
    )


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    branch_id: UUID,
    customer_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
):
    await service.mutate(principal, branch_id, "DELETE", {}, customer_id)
    return Response(status_code=204)
