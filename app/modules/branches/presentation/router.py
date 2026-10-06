from uuid import UUID

from fastapi import APIRouter, status

from app.modules.branches.application.services import (
    CreateStaffAssignment,
    UpdateStaffAssignment,
)
from app.modules.branches.presentation.dependencies import (
    BranchServiceDependency,
    CurrentPrincipal,
)
from app.modules.branches.presentation.schemas import (
    BranchResponse,
    CreateStaffRequest,
    StaffAssignmentResponse,
    UpdateStaffRequest,
)
from app.presentation.errors import ErrorResponse

router = APIRouter(
    prefix="/branches",
    tags=["branches"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)


@router.get("", response_model=list[BranchResponse])
async def list_branches(service: BranchServiceDependency) -> list[BranchResponse]:
    return [
        BranchResponse.model_validate(branch) for branch in await service.list_active()
    ]


@router.get("/{branch_id}", response_model=BranchResponse)
async def get_branch(
    branch_id: UUID, service: BranchServiceDependency
) -> BranchResponse:
    return BranchResponse.model_validate(await service.get_active(branch_id))


@router.get("/{branch_id}/staff", response_model=list[StaffAssignmentResponse])
async def list_staff(
    branch_id: UUID,
    principal: CurrentPrincipal,
    service: BranchServiceDependency,
) -> list[StaffAssignmentResponse]:
    return [
        StaffAssignmentResponse.model_validate(row)
        for row in await service.list_staff(principal, branch_id)
    ]


@router.post(
    "/{branch_id}/staff",
    response_model=StaffAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_staff(
    branch_id: UUID,
    body: CreateStaffRequest,
    principal: CurrentPrincipal,
    service: BranchServiceDependency,
) -> StaffAssignmentResponse:
    command = CreateStaffAssignment(
        user_id=body.user_id,
        role_code=body.role_code,
        employee_code=body.employee_code,
    )
    return StaffAssignmentResponse.model_validate(
        await service.create_staff(principal, branch_id, command)
    )


@router.patch(
    "/{branch_id}/staff/{assignment_id}",
    response_model=StaffAssignmentResponse,
)
async def update_staff(
    branch_id: UUID,
    assignment_id: UUID,
    body: UpdateStaffRequest,
    principal: CurrentPrincipal,
    service: BranchServiceDependency,
) -> StaffAssignmentResponse:
    command = UpdateStaffAssignment(
        role_code=body.role_code,
        employee_code=body.employee_code,
        is_active=body.is_active,
    )
    return StaffAssignmentResponse.model_validate(
        await service.update_staff(principal, branch_id, assignment_id, command)
    )
