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
from app.shared.application.administration import (
    AdministrationConflict,
    AdministrationInvalid,
)
from app.shared.application.audit import AuditRecord, AuditRecorder
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
    def __init__(
        self, repository: BranchRepository, audit: AuditRecorder | None = None
    ) -> None:
        self._repository = repository
        self._audit = audit

    async def _record(
        self,
        principal: Principal,
        assignment: StaffAssignmentData,
        action: str,
        before: StaffAssignmentData | None = None,
    ) -> None:
        if self._audit is not None:
            await self._audit.record(
                AuditRecord(
                    actor_user_id=principal.user_id,
                    branch_id=assignment.branch_id,
                    action=action,
                    entity_type="STAFF_ASSIGNMENT",
                    entity_id=assignment.id,
                    before_state={
                        "role": before.role_code,
                        "is_active": before.is_active,
                    }
                    if before
                    else None,
                    after_state={
                        "role": assignment.role_code,
                        "is_active": assignment.is_active,
                    },
                )
            )

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
        self, principal: Principal, branch_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[StaffAssignmentData]:
        await self.get_active(branch_id)
        await self.require_permission(principal, branch_id, STAFF_MANAGE)
        return await self._repository.list_staff(branch_id, limit, offset)

    async def staff_candidates(
        self, principal: Principal, branch_id: UUID, search: str, limit: int
    ) -> list[dict]:
        await self.require_permission(principal, branch_id, STAFF_MANAGE)
        return await self._repository.staff_candidates(branch_id, search, limit)

    async def create_staff(
        self,
        principal: Principal,
        branch_id: UUID,
        command: CreateStaffAssignment,
    ) -> StaffAssignmentData:
        try:
            await self.get_active(branch_id)
            await self.require_permission(principal, branch_id, STAFF_MANAGE)
            if not await self._repository.lock_branch(branch_id):
                raise BranchNotFoundError()
            await self.require_permission(principal, branch_id, STAFF_MANAGE)
            self._staff_text(command.role_code)
            self._staff_text(command.employee_code)
            if not await self._repository.user_is_assignable(command.user_id):
                raise StaffUserNotFoundError()
            role = await self._repository.get_branch_role(command.role_code)
            if role is None:
                raise StaffRoleNotFoundError()
            if await self._repository.assignment_exists(
                command.user_id, branch_id, role.id
            ):
                raise StaffAssignmentExistsError()
            assignment = await self._repository.add_assignment(
                user_id=command.user_id,
                branch_id=branch_id,
                role=role,
                employee_code=command.employee_code,
            )
            await self._record(principal, assignment, "STAFF_ASSIGNED")
            await self._repository.commit()
            return assignment
        except Exception:
            await self._repository.rollback()
            raise

    @staticmethod
    def _staff_text(value: str) -> None:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 40
            or any(ord(c) < 32 for c in value)
        ):
            raise AdministrationInvalid(
                "INVALID_REQUEST_DATA", "Invalid staff assignment text"
            )

    async def update_staff(
        self,
        principal: Principal,
        branch_id: UUID,
        assignment_id: UUID,
        command: UpdateStaffAssignment,
    ) -> StaffAssignmentData:
        try:
            await self.get_active(branch_id)
            await self.require_permission(principal, branch_id, STAFF_MANAGE)
            if not await self._repository.lock_branch(branch_id):
                raise BranchNotFoundError()
            await self.require_permission(principal, branch_id, STAFF_MANAGE)
            assignment = await self._repository.get_assignment(branch_id, assignment_id)
            if assignment is None:
                raise StaffAssignmentNotFoundError()
            if command.role_code is not None:
                self._staff_text(command.role_code)
            if command.employee_code is not None:
                self._staff_text(command.employee_code)
            role = await self._repository.get_branch_role(
                command.role_code or assignment.role_code
            )
            if role is None:
                raise StaffRoleNotFoundError()
            employee_code = command.employee_code or assignment.employee_code
            is_active = (
                command.is_active
                if command.is_active is not None
                else assignment.is_active
            )
            if is_active and not await self._repository.user_is_assignable(
                assignment.user_id
            ):
                raise StaffUserNotFoundError()
            if (
                assignment.is_active
                and assignment.role_code == "ADMIN"
                and (not is_active or role.code != "ADMIN")
            ):
                if not await self._repository.other_active_admin_exists(
                    branch_id, assignment_id
                ):
                    raise AdministrationConflict(
                        "LAST_BRANCH_ADMIN",
                        "An active branch must retain an active administrator",
                    )
            ended_at = None if is_active else assignment.ended_at or utc_now()
            updated = await self._repository.update_assignment(
                assignment,
                role=role,
                employee_code=employee_code,
                is_active=is_active,
                ended_at=ended_at,
            )
            await self._record(
                principal,
                updated,
                "STAFF_UPDATED" if is_active else "STAFF_DEACTIVATED",
                assignment,
            )
            await self._repository.commit()
            return updated
        except Exception:
            await self._repository.rollback()
            raise
