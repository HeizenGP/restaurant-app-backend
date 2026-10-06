import asyncio
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.auth.presentation.dependencies import get_current_principal
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
    BranchRoleData,
    StaffAssignmentData,
)
from app.modules.branches.application.services import (
    BranchService,
    CreateStaffAssignment,
    UpdateStaffAssignment,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.branches.presentation.dependencies import get_branch_service
from app.modules.branches.presentation.router import router
from app.presentation.errors import register_exception_handlers
from app.shared.domain.time import utc_now


class MemoryBranchRepository:
    def __init__(self) -> None:
        self.branch_a = uuid4()
        self.branch_b = uuid4()
        self.inactive = uuid4()
        self.admin = uuid4()
        self.employee = uuid4()
        self.branches = {
            key: BranchData(
                id=key,
                code=code,
                name=code,
                address_line="Jr. Lima 123",
                district="Tarapoto",
                city="Tarapoto",
                department="San Martín",
                latitude=None,
                longitude=None,
                phone=None,
                timezone="America/Lima",
            )
            for key, code in (
                (self.branch_a, "A"),
                (self.branch_b, "B"),
                (self.inactive, "INACTIVE"),
            )
        }
        self.active_ids = {self.branch_a, self.branch_b}
        self.grants = {(self.admin, self.branch_a, "STAFF_MANAGE")}
        self.assignable = {self.admin, self.employee}
        self.roles = {
            "ADMIN": BranchRoleData(id=2, code="ADMIN"),
            "KITCHEN": BranchRoleData(id=3, code="KITCHEN"),
        }
        self.staff: dict[UUID, StaffAssignmentData] = {}
        self.commits = 0
        self.rollbacks = 0

    async def list_active(self) -> list[BranchData]:
        return [row for key, row in self.branches.items() if key in self.active_ids]

    async def get_active(self, branch_id: UUID) -> BranchData | None:
        return self.branches.get(branch_id) if branch_id in self.active_ids else None

    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission_code: str
    ) -> bool:
        return (user_id, branch_id, permission_code) in self.grants

    async def user_is_assignable(self, user_id: UUID) -> bool:
        return user_id in self.assignable

    async def get_branch_role(self, role_code: str) -> BranchRoleData | None:
        return self.roles.get(role_code.upper())

    async def assignment_exists(
        self, user_id: UUID, branch_id: UUID, role_id: int
    ) -> bool:
        return any(
            (row.user_id, row.branch_id, row.role_id) == (user_id, branch_id, role_id)
            for row in self.staff.values()
        )

    async def list_staff(self, branch_id: UUID) -> list[StaffAssignmentData]:
        return [row for row in self.staff.values() if row.branch_id == branch_id]

    async def get_assignment(
        self, branch_id: UUID, assignment_id: UUID
    ) -> StaffAssignmentData | None:
        row = self.staff.get(assignment_id)
        return row if row and row.branch_id == branch_id else None

    async def add_assignment(
        self,
        *,
        user_id: UUID,
        branch_id: UUID,
        role: BranchRoleData,
        employee_code: str,
    ) -> StaffAssignmentData:
        row = StaffAssignmentData(
            id=uuid4(),
            user_id=user_id,
            branch_id=branch_id,
            role_id=role.id,
            role_code=role.code,
            employee_code=employee_code,
            is_active=True,
            assigned_at=utc_now(),
            ended_at=None,
        )
        self.staff[row.id] = row
        return row

    async def update_assignment(
        self,
        assignment: StaffAssignmentData,
        *,
        role: BranchRoleData,
        employee_code: str,
        is_active: bool,
        ended_at: datetime | None,
    ) -> StaffAssignmentData:
        row = replace(
            assignment,
            role_id=role.id,
            role_code=role.code,
            employee_code=employee_code,
            is_active=is_active,
            ended_at=ended_at,
        )
        self.staff[row.id] = row
        return row

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def repository() -> MemoryBranchRepository:
    return MemoryBranchRepository()


def admin(repository: MemoryBranchRepository) -> Principal:
    return Principal(principal_type=PrincipalType.REGISTERED, user_id=repository.admin)


def test_public_listing_filters_inactive_and_detail_hides_missing(
    repository: MemoryBranchRepository,
) -> None:
    service = BranchService(repository)
    rows = asyncio.run(service.list_active())
    assert {row.id for row in rows} == repository.active_ids
    for branch_id in (repository.inactive, uuid4()):
        with pytest.raises(BranchNotFoundError):
            asyncio.run(service.get_active(branch_id))


def test_admin_manages_only_own_branch_and_revocation_takes_effect(
    repository: MemoryBranchRepository,
) -> None:
    async def scenario() -> None:
        service = BranchService(repository)
        assert await service.list_staff(admin(repository), repository.branch_a) == []
        with pytest.raises(StaffForbiddenError):
            await service.list_staff(admin(repository), repository.branch_b)
        repository.grants.clear()
        with pytest.raises(StaffForbiddenError):
            await service.list_staff(admin(repository), repository.branch_a)

    asyncio.run(scenario())


@pytest.mark.parametrize("guest", [True, False])
def test_guest_and_customer_cannot_manage_staff(
    repository: MemoryBranchRepository, guest: bool
) -> None:
    principal = (
        Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())
        if guest
        else Principal(
            principal_type=PrincipalType.REGISTERED, user_id=repository.employee
        )
    )
    with pytest.raises(StaffForbiddenError):
        asyncio.run(
            BranchService(repository).list_staff(principal, repository.branch_a)
        )


@pytest.mark.parametrize("role", ["CUSTOMER", "GLOBAL_ADMIN", "MISSING"])
def test_global_or_unknown_roles_cannot_be_staff(
    repository: MemoryBranchRepository, role: str
) -> None:
    with pytest.raises(StaffRoleNotFoundError):
        asyncio.run(
            BranchService(repository).create_staff(
                admin(repository),
                repository.branch_a,
                CreateStaffAssignment(
                    user_id=repository.employee, role_code=role, employee_code="E01"
                ),
            )
        )


def test_staff_creation_duplicates_and_traceable_deactivation(
    repository: MemoryBranchRepository,
) -> None:
    async def scenario() -> None:
        service = BranchService(repository)
        command = CreateStaffAssignment(
            user_id=repository.employee, role_code="KITCHEN", employee_code="E01"
        )
        created = await service.create_staff(
            admin(repository), repository.branch_a, command
        )
        assert created.is_active and repository.commits == 1
        with pytest.raises(StaffAssignmentExistsError):
            await service.create_staff(admin(repository), repository.branch_a, command)
        ended = await service.update_staff(
            admin(repository),
            repository.branch_a,
            created.id,
            UpdateStaffAssignment(is_active=False),
        )
        assert not ended.is_active and ended.ended_at is not None
        assert len(repository.staff) == 1
        with pytest.raises(StaffAssignmentNotFoundError):
            await service.update_staff(
                admin(repository),
                repository.branch_a,
                uuid4(),
                UpdateStaffAssignment(is_active=False),
            )

    asyncio.run(scenario())


def test_assignment_requires_active_existing_user(
    repository: MemoryBranchRepository,
) -> None:
    with pytest.raises(StaffUserNotFoundError):
        asyncio.run(
            BranchService(repository).create_staff(
                admin(repository),
                repository.branch_a,
                CreateStaffAssignment(
                    user_id=uuid4(), role_code="KITCHEN", employee_code="E01"
                ),
            )
        )


def test_authorization_query_consults_current_branch_user_roles_permissions() -> None:
    session = MagicMock(spec=AsyncSession)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    allowed = asyncio.run(
        SQLAlchemyBranchRepository(session).has_permission(
            uuid4(), uuid4(), "STAFF_MANAGE"
        )
    )
    assert not allowed
    query = str(session.execute.await_args.args[0])
    for table in (
        "users",
        "branches",
        "roles",
        "permissions",
        "role_permissions",
        "staff_assignments",
    ):
        assert table in query
    for clause in (
        "users.deleted_at IS NULL",
        "branches.deleted_at IS NULL",
        "staff_assignments.ended_at IS NULL",
        "staff_assignments.is_active IS true",
    ):
        assert clause in query


def test_branch_api_public_private_and_validation(
    repository: MemoryBranchRepository,
) -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_branch_service] = lambda: BranchService(repository)
    app.dependency_overrides[get_current_principal] = lambda: admin(repository)
    with TestClient(app) as client:
        listed = client.get("/api/v1/branches")
        assert listed.status_code == 200
        assert len(listed.json()) == 2
        assert "deleted_at" not in listed.text
        assert client.get(f"/api/v1/branches/{repository.inactive}").status_code == 404
        assert (
            client.get(f"/api/v1/branches/{repository.branch_b}/staff").status_code
            == 403
        )
        path = f"/api/v1/branches/{repository.branch_a}/staff"
        created = client.post(
            path,
            json={
                "user_id": str(repository.employee),
                "role_code": "KITCHEN",
                "employee_code": "E01",
            },
        )
        assert created.status_code == 201
        item_path = path + "/" + created.json()["id"]
        assert client.patch(item_path, json={"is_active": None}).status_code == 422
        assert (
            client.patch(item_path, json={"is_active": False}).json()["ended_at"]
            is not None
        )
