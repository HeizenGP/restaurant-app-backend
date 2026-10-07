import asyncio
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.modules.branches.application.errors import (
    StaffForbiddenError,
    StaffUserNotFoundError,
)
from app.modules.branches.application.services import (
    BranchService,
    UpdateStaffAssignment,
)
from app.shared.application.administration import AdministrationConflict
from app.shared.domain.time import utc_now
from tests.modules.branches.test_branches import MemoryBranchRepository, admin


async def add_admin(repo, user=None, code="ADMIN-1"):
    return await repo.add_assignment(
        user_id=user or repo.admin,
        branch_id=repo.branch_a,
        role=repo.roles["ADMIN"],
        employee_code=code,
    )


@pytest.mark.parametrize(
    "command",
    [
        UpdateStaffAssignment(is_active=False),
        UpdateStaffAssignment(role_code="KITCHEN"),
    ],
)
def test_last_active_administrator_cannot_be_deactivated_or_demoted(command):
    repo = MemoryBranchRepository()

    async def scenario():
        assignment = await add_admin(repo)
        audit = AsyncMock()
        with pytest.raises(AdministrationConflict) as exc:
            await BranchService(repo, audit).update_staff(
                admin(repo), repo.branch_a, assignment.id, command
            )
        assert exc.value.code == "LAST_BRANCH_ADMIN"
        assert (
            repo.staff[assignment.id].is_active
            and repo.staff[assignment.id].role_code == "ADMIN"
        )
        assert repo.rollbacks == 1 and repo.commits == 0
        audit.record.assert_not_called()

    asyncio.run(scenario())


def test_another_active_admin_allows_self_deactivation_and_reactivation():
    repo = MemoryBranchRepository()

    async def scenario():
        assignment = await add_admin(repo)
        await add_admin(repo, repo.employee, "ADMIN-2")
        audit = AsyncMock()
        service = BranchService(repo, audit)
        deactivated = await service.update_staff(
            admin(repo),
            repo.branch_a,
            assignment.id,
            UpdateStaffAssignment(is_active=False),
        )
        assert not deactivated.is_active and deactivated.ended_at is not None
        repo.grants.remove((repo.admin, repo.branch_a, "STAFF_MANAGE"))
        with pytest.raises(StaffForbiddenError):
            await service.update_staff(
                admin(repo),
                repo.branch_a,
                assignment.id,
                UpdateStaffAssignment(is_active=True),
            )
        repo.grants.add((repo.employee, repo.branch_a, "STAFF_MANAGE"))
        reactivated = await service.update_staff(
            replace(admin(repo), user_id=repo.employee),
            repo.branch_a,
            assignment.id,
            UpdateStaffAssignment(is_active=True),
        )
        assert reactivated.is_active and reactivated.ended_at is None
        assert len(repo.staff) == 2
        assert [args.args[0].action for args in audit.record.await_args_list] == [
            "STAFF_DEACTIVATED",
            "STAFF_UPDATED",
        ]

    asyncio.run(scenario())


def test_reactivation_requires_current_active_user():
    repo = MemoryBranchRepository()

    async def scenario():
        assignment = await repo.add_assignment(
            user_id=repo.employee,
            branch_id=repo.branch_a,
            role=repo.roles["KITCHEN"],
            employee_code="K",
        )
        repo.staff[assignment.id] = replace(
            assignment, is_active=False, ended_at=utc_now()
        )
        repo.assignable.remove(repo.employee)
        with pytest.raises(StaffUserNotFoundError):
            await BranchService(repo).update_staff(
                admin(repo),
                repo.branch_a,
                assignment.id,
                UpdateStaffAssignment(is_active=True),
            )
        assert not repo.staff[assignment.id].is_active

    asyncio.run(scenario())


def test_future_assigned_admin_does_not_allow_last_current_admin_to_leave():
    async def scenario():
        repo = MemoryBranchRepository()
        current = await add_admin(repo)
        future = await add_admin(repo, repo.employee, "FUTURE-ADMIN")
        repo.staff[future.id] = replace(
            future, assigned_at=utc_now() + timedelta(days=1)
        )
        with pytest.raises(AdministrationConflict) as exc:
            await BranchService(repo).update_staff(
                admin(repo),
                repo.branch_a,
                current.id,
                UpdateStaffAssignment(is_active=False),
            )
        assert exc.value.code == "LAST_BRANCH_ADMIN"

    asyncio.run(scenario())


def test_simulated_two_self_deactivations_serialize_and_retain_one_admin():
    async def scenario():
        first = MemoryBranchRepository()
        a = await add_admin(first)
        b = await add_admin(first, first.employee, "ADMIN-2")
        first.grants.add((first.employee, first.branch_a, "STAFF_MANAGE"))
        lock = asyncio.Lock()

        class LockedRepository(MemoryBranchRepository):
            def __init__(self):
                self.__dict__ = first.__dict__.copy()
                self.held = False

            async def lock_branch(self, branch_id):
                await lock.acquire()
                self.held = True
                return branch_id in self.active_ids

            async def commit(self):
                self.commits += 1
                if self.held:
                    self.held = False
                    lock.release()

            async def rollback(self):
                self.rollbacks += 1
                if self.held:
                    self.held = False
                    lock.release()

        async def deactivate(user, assignment):
            actor = replace(admin(first), user_id=user)
            repo = LockedRepository()
            try:
                await BranchService(repo).update_staff(
                    actor,
                    first.branch_a,
                    assignment.id,
                    UpdateStaffAssignment(is_active=False),
                )
                return "OK"
            except AdministrationConflict as exc:
                return exc.code

        outcomes = await asyncio.gather(
            deactivate(first.admin, a), deactivate(first.employee, b)
        )
        assert sorted(outcomes) == ["LAST_BRANCH_ADMIN", "OK"]
        assert (
            sum(
                row.is_active and row.role_code == "ADMIN"
                for row in first.staff.values()
            )
            == 1
        )

    asyncio.run(scenario())
