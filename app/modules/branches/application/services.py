from dataclasses import dataclass
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.branches.application.errors import (
    BranchNotFoundError,
    StaffAssignmentExistsError,
    StaffAssignmentNotFoundError,
    StaffForbiddenError,
    StaffRoleNotFoundError,
    StaffUserNotFoundError,
)
from app.modules.branches.application.ports import (
    BranchData,
    BranchRepository,
    StaffAssignmentData,
)
from app.shared.domain.time import utc_now

STAFF_MANAGE = "STAFF_MANAGE"


@dataclass(frozen=True)
class CreateStaffAssignment:
    user_id: UUID
    role_code: str
    employee_code: str


@dataclass(frozen=True)
class UpdateStaffAssignment:
    role_code: str | None = None
    employee_code: str | None = None
    is_active: bool | None = None


class BranchService:
    def __init__(self, repository: BranchRepository) -> None:
        self._repository = repository

    async def list_active(self) -> list[BranchData]:
        return await self._repository.list_active()

    async def get_active(self, branch_id: UUID) -> BranchData:
        branch = await self._repository.get_active(branch_id)
        if branch is None:
            raise BranchNotFoundError()
        return branch

    async def require_permission(
        self, principal: Principal, branch_id: UUID, permission_code: str
    ) -> None:
        if (
            principal.principal_type is not PrincipalType.REGISTERED
            or principal.user_id is None
        ):
            raise StaffForbiddenError()
        allowed = await self._repository.has_permission(
            principal.user_id, branch_id, permission_code
        )
        if not allowed:
            raise StaffForbiddenError()

    async def list_staff(
        self, principal: Principal, branch_id: UUID
    ) -> list[StaffAssignmentData]:
        await self.get_active(branch_id)
        await self.require_permission(principal, branch_id, STAFF_MANAGE)
        return await self._repository.list_staff(branch_id)

    async def create_staff(
        self,
        principal: Principal,
        branch_id: UUID,
        command: CreateStaffAssignment,
    ) -> StaffAssignmentData:
        await self.get_active(branch_id)
        await self.require_permission(principal, branch_id, STAFF_MANAGE)
        if not await self._repository.user_is_assignable(command.user_id):
            raise StaffUserNotFoundError()
        role = await self._repository.get_branch_role(command.role_code)
        if role is None:
            raise StaffRoleNotFoundError()
        if await self._repository.assignment_exists(
            command.user_id, branch_id, role.id
        ):
            raise StaffAssignmentExistsError()
        try:
            assignment = await self._repository.add_assignment(
                user_id=command.user_id,
                branch_id=branch_id,
                role=role,
                employee_code=command.employee_code,
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return assignment

    async def update_staff(
        self,
        principal: Principal,
        branch_id: UUID,
        assignment_id: UUID,
        command: UpdateStaffAssignment,
    ) -> StaffAssignmentData:
        await self.get_active(branch_id)
        await self.require_permission(principal, branch_id, STAFF_MANAGE)
        assignment = await self._repository.get_assignment(branch_id, assignment_id)
        if assignment is None:
            raise StaffAssignmentNotFoundError()
        role = (
            await self._repository.get_branch_role(command.role_code)
            if command.role_code is not None
            else await self._repository.get_branch_role(assignment.role_code)
        )
        if role is None:
            raise StaffRoleNotFoundError()
        employee_code = command.employee_code or assignment.employee_code
        is_active = (
            command.is_active if command.is_active is not None else assignment.is_active
        )
        ended_at = None if is_active else assignment.ended_at or utc_now()
        try:
            updated = await self._repository.update_assignment(
                assignment,
                role=role,
                employee_code=employee_code,
                is_active=is_active,
                ended_at=ended_at,
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return updated
