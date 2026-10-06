from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class BranchHourData:
    day_of_week: int
    open_time: time | None
    close_time: time | None
    is_closed: bool


@dataclass(frozen=True)
class BranchData:
    id: UUID
    code: str
    name: str
    address_line: str
    district: str | None
    city: str
    department: str
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    timezone: str
    hours: tuple[BranchHourData, ...] = ()


@dataclass(frozen=True)
class BranchRoleData:
    id: int
    code: str


@dataclass(frozen=True)
class StaffAssignmentData:
    id: UUID
    user_id: UUID
    branch_id: UUID
    role_id: int
    role_code: str
    employee_code: str
    is_active: bool
    assigned_at: datetime
    ended_at: datetime | None


class BranchRepository(Protocol):
    async def list_active(self) -> list[BranchData]: ...

    async def get_active(self, branch_id: UUID) -> BranchData | None: ...

    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission_code: str
    ) -> bool: ...

    async def user_is_assignable(self, user_id: UUID) -> bool: ...

    async def get_branch_role(self, role_code: str) -> BranchRoleData | None: ...

    async def assignment_exists(
        self, user_id: UUID, branch_id: UUID, role_id: int
    ) -> bool: ...

    async def list_staff(self, branch_id: UUID) -> list[StaffAssignmentData]: ...

    async def get_assignment(
        self, branch_id: UUID, assignment_id: UUID
    ) -> StaffAssignmentData | None: ...

    async def add_assignment(
        self,
        *,
        user_id: UUID,
        branch_id: UUID,
        role: BranchRoleData,
        employee_code: str,
    ) -> StaffAssignmentData: ...

    async def update_assignment(
        self,
        assignment: StaffAssignmentData,
        *,
        role: BranchRoleData,
        employee_code: str,
        is_active: bool,
        ended_at: datetime | None,
    ) -> StaffAssignmentData: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
