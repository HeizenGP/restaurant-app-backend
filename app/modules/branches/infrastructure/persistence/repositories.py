from collections import defaultdict
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.infrastructure.persistence.models import (
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    UserModel,
)
from app.modules.branches.application.errors import (
    StaffAssignmentExistsError,
    StaffAssignmentNotFoundError,
)
from app.modules.branches.application.ports import (
    BranchData,
    BranchHourData,
    BranchRoleData,
    StaffAssignmentData,
)
from app.modules.branches.infrastructure.persistence.models import (
    BranchHourModel,
    BranchModel,
    StaffAssignmentModel,
)
from app.shared.domain.time import utc_now


class SQLAlchemyBranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _staff_data(
        assignment: StaffAssignmentModel, role_code: str
    ) -> StaffAssignmentData:
        return StaffAssignmentData(
            id=assignment.id,
            user_id=assignment.user_id,
            branch_id=assignment.branch_id,
            role_id=assignment.role_id,
            role_code=role_code,
            employee_code=assignment.employee_code,
            is_active=assignment.is_active,
            assigned_at=assignment.assigned_at,
            ended_at=assignment.ended_at,
        )

    async def _with_hours(self, branches: list[BranchModel]) -> list[BranchData]:
        branch_ids = [branch.id for branch in branches]
        grouped: dict[UUID, list[BranchHourData]] = defaultdict(list)
        if branch_ids:
            rows = await self._session.execute(
                select(BranchHourModel)
                .where(BranchHourModel.branch_id.in_(branch_ids))
                .order_by(BranchHourModel.day_of_week)
            )
            for hour in rows.scalars():
                grouped[hour.branch_id].append(
                    BranchHourData(
                        day_of_week=hour.day_of_week,
                        open_time=hour.open_time,
                        close_time=hour.close_time,
                        is_closed=hour.is_closed,
                    )
                )
        return [
            BranchData(
                id=branch.id,
                code=branch.code,
                name=branch.name,
                address_line=branch.address_line,
                district=branch.district,
                city=branch.city,
                department=branch.department,
                latitude=branch.latitude,
                longitude=branch.longitude,
                phone=branch.phone,
                timezone=branch.timezone,
                hours=tuple(grouped[branch.id]),
            )
            for branch in branches
        ]

    async def list_active(self) -> list[BranchData]:
        rows = await self._session.execute(
            select(BranchModel)
            .where(
                BranchModel.is_active.is_(True),
                BranchModel.deleted_at.is_(None),
            )
            .order_by(BranchModel.name)
        )
        return await self._with_hours(list(rows.scalars()))

    async def get_active(self, branch_id: UUID) -> BranchData | None:
        row = await self._session.execute(
            select(BranchModel).where(
                BranchModel.id == branch_id,
                BranchModel.is_active.is_(True),
                BranchModel.deleted_at.is_(None),
            )
        )
        branch = row.scalar_one_or_none()
        if branch is None:
            return None
        return (await self._with_hours([branch]))[0]

    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission_code: str
    ) -> bool:
        query = (
            select(StaffAssignmentModel.id)
            .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
            .join(BranchModel, BranchModel.id == StaffAssignmentModel.branch_id)
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
            .join(
                PermissionModel,
                PermissionModel.id == RolePermissionModel.permission_id,
            )
            .where(
                StaffAssignmentModel.user_id == user_id,
                StaffAssignmentModel.branch_id == branch_id,
                StaffAssignmentModel.is_active.is_(True),
                StaffAssignmentModel.ended_at.is_(None),
                RoleModel.scope == "BRANCH",
                PermissionModel.code == permission_code,
                UserModel.account_status == "ACTIVE",
                UserModel.deleted_at.is_(None),
                BranchModel.is_active.is_(True),
                BranchModel.deleted_at.is_(None),
            )
            .limit(1)
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None

    async def user_is_assignable(self, user_id: UUID) -> bool:
        query = select(UserModel.id).where(
            UserModel.id == user_id,
            UserModel.account_status == "ACTIVE",
            UserModel.deleted_at.is_(None),
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None

    async def staff_is_active(
        self, user_id: UUID, branch_id: UUID, now: datetime
    ) -> bool:
        """Branch-scoped staff eligibility; hold SHARE through caller commit."""
        query = (
            select(StaffAssignmentModel.id)
            .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
            .join(BranchModel, BranchModel.id == StaffAssignmentModel.branch_id)
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .where(
                StaffAssignmentModel.user_id == user_id,
                StaffAssignmentModel.branch_id == branch_id,
                StaffAssignmentModel.is_active.is_(True),
                StaffAssignmentModel.assigned_at <= now,
                StaffAssignmentModel.ended_at.is_(None),
                UserModel.account_status == "ACTIVE",
                UserModel.deleted_at.is_(None),
                BranchModel.is_active.is_(True),
                BranchModel.deleted_at.is_(None),
                RoleModel.scope == "BRANCH",
            )
            .limit(1)
            .with_for_update(read=True, of=(StaffAssignmentModel, UserModel))
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None

    async def get_branch_role(self, role_code: str) -> BranchRoleData | None:
        row = await self._session.execute(
            select(RoleModel).where(
                RoleModel.code == role_code.upper(), RoleModel.scope == "BRANCH"
            )
        )
        role = row.scalar_one_or_none()
        return (
            None
            if role is None or role.id is None
            else BranchRoleData(id=role.id, code=role.code)
        )

    async def assignment_exists(
        self, user_id: UUID, branch_id: UUID, role_id: int
    ) -> bool:
        row = await self._session.execute(
            select(StaffAssignmentModel.id).where(
                StaffAssignmentModel.user_id == user_id,
                StaffAssignmentModel.branch_id == branch_id,
                StaffAssignmentModel.role_id == role_id,
            )
        )
        return row.scalar_one_or_none() is not None

    async def list_staff(self, branch_id: UUID) -> list[StaffAssignmentData]:
        rows = await self._session.execute(
            select(StaffAssignmentModel, RoleModel.code)
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .where(StaffAssignmentModel.branch_id == branch_id)
            .order_by(StaffAssignmentModel.assigned_at)
        )
        return [self._staff_data(item, code) for item, code in rows.all()]

    async def get_assignment(
        self, branch_id: UUID, assignment_id: UUID
    ) -> StaffAssignmentData | None:
        row = await self._session.execute(
            select(StaffAssignmentModel, RoleModel.code)
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .where(
                StaffAssignmentModel.id == assignment_id,
                StaffAssignmentModel.branch_id == branch_id,
            )
            .with_for_update(of=StaffAssignmentModel)
        )
        result = row.one_or_none()
        return None if result is None else self._staff_data(result[0], result[1])

    async def add_assignment(
        self,
        *,
        user_id: UUID,
        branch_id: UUID,
        role: BranchRoleData,
        employee_code: str,
    ) -> StaffAssignmentData:
        now = utc_now()
        model = StaffAssignmentModel(
            id=uuid4(),
            user_id=user_id,
            branch_id=branch_id,
            role_id=role.id,
            employee_code=employee_code,
            is_active=True,
            assigned_at=now,
            ended_at=None,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError:
            raise StaffAssignmentExistsError() from None
        return self._staff_data(model, role.code)

    async def update_assignment(
        self,
        assignment: StaffAssignmentData,
        *,
        role: BranchRoleData,
        employee_code: str,
        is_active: bool,
        ended_at: datetime | None,
    ) -> StaffAssignmentData:
        model = await self._session.get(StaffAssignmentModel, assignment.id)
        if model is None:
            raise StaffAssignmentNotFoundError()
        model.role_id = role.id
        model.employee_code = employee_code
        model.is_active = is_active
        model.ended_at = ended_at
        try:
            await self._session.flush()
        except IntegrityError:
            raise StaffAssignmentExistsError() from None
        return self._staff_data(model, role.code)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
