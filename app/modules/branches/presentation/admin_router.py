from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    SessionDependency,
)
from app.modules.branches.application.admin_services import BranchAdministrationService
from app.modules.branches.application.services import (
    CreateStaffAssignment,
    UpdateStaffAssignment,
)
from app.modules.branches.infrastructure.persistence.admin_repository import (
    SQLAlchemyBranchAdministrationRepository,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.branches.presentation.admin_schemas import (
    AdministrativeBranchResponse,
    CandidateQuery,
    CandidateResponse,
    CreateBranchRequest,
    HourInput,
    HoursInput,
    Pagination,
    UpdateBranchRequest,
)
from app.modules.branches.presentation.dependencies import BranchServiceDependency
from app.modules.branches.presentation.schemas import (
    CreateStaffRequest,
    StaffAssignmentResponse,
    UpdateStaffRequest,
)
from app.modules.orders.infrastructure.branch_administration import (
    SQLAlchemyBranchOrderConfiguration,
)
from app.presentation.errors import ErrorResponse
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder

router = APIRouter(
    prefix="/admin/branches",
    tags=["admin branches"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)


def get_branch_administration_service(
    session: SessionDependency,
) -> BranchAdministrationService:
    return BranchAdministrationService(
        SQLAlchemyBranchRepository(session),
        SQLAlchemyBranchAdministrationRepository(session),
        SQLAlchemyBranchOrderConfiguration(session),
        SQLAlchemyAuditRecorder(session),
    )


Service = Annotated[
    BranchAdministrationService, Depends(get_branch_administration_service)
]


@router.get("", response_model=list[AdministrativeBranchResponse])
async def list_branches(
    principal: CurrentRegisteredUser,
    service: Service,
    query: Annotated[Pagination, Query()],
):
    return await service.list(principal, query.limit, query.offset)


@router.post("", status_code=201, response_model=AdministrativeBranchResponse)
async def create_branch(
    body: CreateBranchRequest, principal: CurrentRegisteredUser, service: Service
):
    return await service.create(principal, body.model_dump())


@router.get("/{branch_id}", response_model=AdministrativeBranchResponse)
async def get_branch(
    branch_id: UUID, principal: CurrentRegisteredUser, service: Service
):
    return await service.get(principal, branch_id)


@router.patch("/{branch_id}", response_model=AdministrativeBranchResponse)
async def update_branch(
    branch_id: UUID,
    body: UpdateBranchRequest,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.mutate(
        principal, branch_id, "UPDATE", body.model_dump(exclude_unset=True)
    )


@router.delete("/{branch_id}", status_code=204)
async def deactivate_branch(
    branch_id: UUID, principal: CurrentRegisteredUser, service: Service
):
    await service.mutate(principal, branch_id, "DELETE", {})
    return Response(status_code=204)


@router.get("/{branch_id}/hours", response_model=list[HourInput])
async def get_hours(
    branch_id: UUID, principal: CurrentRegisteredUser, service: Service
):
    return (await service.get(principal, branch_id))["hours"]


@router.put("/{branch_id}/hours", response_model=list[HourInput])
async def replace_hours(
    branch_id: UUID,
    body: HoursInput,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.mutate(principal, branch_id, "HOURS", body.model_dump())


@router.get("/{branch_id}/staff/candidates", response_model=list[CandidateResponse])
async def staff_candidates(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: BranchServiceDependency,
    query: Annotated[CandidateQuery, Query()],
):
    return await service.staff_candidates(
        principal, branch_id, query.search, query.limit
    )


@router.get("/{branch_id}/staff", response_model=list[StaffAssignmentResponse])
async def list_staff(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: BranchServiceDependency,
    query: Annotated[Pagination, Query()],
):
    return await service.list_staff(principal, branch_id, query.limit, query.offset)


@router.post(
    "/{branch_id}/staff", response_model=StaffAssignmentResponse, status_code=201
)
async def create_staff(
    branch_id: UUID,
    body: CreateStaffRequest,
    principal: CurrentRegisteredUser,
    service: BranchServiceDependency,
):
    return await service.create_staff(
        principal, branch_id, CreateStaffAssignment(**body.model_dump())
    )


@router.patch(
    "/{branch_id}/staff/{assignment_id}", response_model=StaffAssignmentResponse
)
async def update_staff(
    branch_id: UUID,
    assignment_id: UUID,
    body: UpdateStaffRequest,
    principal: CurrentRegisteredUser,
    service: BranchServiceDependency,
):
    return await service.update_staff(
        principal, branch_id, assignment_id, UpdateStaffAssignment(**body.model_dump())
    )


@router.delete("/{branch_id}/staff/{assignment_id}", status_code=204)
async def deactivate_staff(
    branch_id: UUID,
    assignment_id: UUID,
    principal: CurrentRegisteredUser,
    service: BranchServiceDependency,
):
    await service.update_staff(
        principal, branch_id, assignment_id, UpdateStaffAssignment(is_active=False)
    )
    return Response(status_code=204)
