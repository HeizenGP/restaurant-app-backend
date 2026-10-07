from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import String, func, or_, select
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
from app.shared.application.administration import AdministrativeBranch
from app.shared.domain.time import utc_now


def administrative_branch_query(user_id: UUID, permission: str):
    query = (
        select(BranchModel.id, BranchModel.name, BranchModel.timezone)
        .join(StaffAssignmentModel, StaffAssignmentModel.branch_id == BranchModel.id)
        .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
        .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
        .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
        .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
        .where(
            StaffAssignmentModel.user_id == user_id,
            StaffAssignmentModel.is_active.is_(True),
            StaffAssignmentModel.ended_at.is_(None),
            StaffAssignmentModel.assigned_at <= func.now(),
            RoleModel.scope == "BRANCH",
            PermissionModel.code == permission,
            UserModel.account_status == "ACTIVE",
            UserModel.deleted_at.is_(None),
            BranchModel.is_active.is_(True),
            BranchModel.deleted_at.is_(None),
        )
        .distinct()
        .order_by(BranchModel.id)
    )
    if permission == "BRANCH_CREATE":
        query = query.where(RoleModel.code == "ADMIN")
    return query


class SQLAlchemyBranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_branch(self, branch_id: UUID) -> bool:
        return (
            await self._session.execute(
                select(BranchModel.id)
                .where(
                    BranchModel.id == branch_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none() is not None

    async def other_active_admin_exists(
        self, branch_id: UUID, assignment_id: UUID
    ) -> bool:
        query = (
            select(StaffAssignmentModel.id)
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
            .where(
                StaffAssignmentModel.branch_id == branch_id,
                StaffAssignmentModel.id != assignment_id,
                StaffAssignmentModel.is_active.is_(True),
                StaffAssignmentModel.ended_at.is_(None),
                StaffAssignmentModel.assigned_at <= func.now(),
                RoleModel.code == "ADMIN",
                RoleModel.scope == "BRANCH",
                UserModel.account_status == "ACTIVE",
                UserModel.deleted_at.is_(None),
            )
            .limit(1)
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None

    async def authorized_branches(
        self, user_id: UUID, permission: str, *, branch_id: UUID | None = None
    ) -> tuple[AdministrativeBranch, ...]:
        query = administrative_branch_query(user_id, permission)
        if branch_id is not None:
            query = query.where(BranchModel.id == branch_id)
        query = query.limit(101)
        return tuple(
            AdministrativeBranch(*row)
            for row in (await self._session.execute(query)).all()
        )

    async def has_any_permission(self, user_id: UUID, permission: str) -> bool:
        return (
            await self._session.execute(
                administrative_branch_query(user_id, permission).limit(1)
            )
        ).first() is not None

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
                StaffAssignmentModel.assigned_at <= func.now(),
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

    async def list_staff(
        self, branch_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[StaffAssignmentData]:
        rows = await self._session.execute(
            select(
                StaffAssignmentModel,
                RoleModel.code,
                UserModel.first_name,
                UserModel.last_name,
                UserModel.email,
                UserModel.phone,
                UserModel.account_status,
            )
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
            .where(StaffAssignmentModel.branch_id == branch_id)
            .order_by(StaffAssignmentModel.assigned_at, StaffAssignmentModel.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            replace(
                self._staff_data(row[0], row[1]),
                first_name=row[2],
                last_name=row[3],
                email=row[4],
                phone=row[5],
                account_status=row[6],
            )
            for row in rows.all()
        ]

    async def staff_candidates(
        self, branch_id: UUID, search: str, limit: int
    ) -> list[dict]:
        pattern = (
            search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        assigned = (
            select(StaffAssignmentModel.id)
            .where(
                StaffAssignmentModel.branch_id == branch_id,
                StaffAssignmentModel.user_id == UserModel.id,
            )
            .exists()
        )
        query = (
            select(
                UserModel.id,
                UserModel.first_name,
                UserModel.last_name,
                UserModel.email,
                UserModel.phone,
                UserModel.account_status,
                assigned.label("already_assigned"),
            )
            .where(
                UserModel.account_status == "ACTIVE",
                UserModel.deleted_at.is_(None),
                or_(
                    func.lower(
                        UserModel.first_name
                        + " "
                        + func.coalesce(UserModel.last_name, "")
                    ).like(pattern.lower()),
                    func.lower(UserModel.last_name).like(pattern.lower()),
                    func.lower(UserModel.email.cast(String)).like(pattern.lower()),
                    UserModel.phone.like(pattern),
                ),
            )
            .order_by(UserModel.first_name, UserModel.id)
            .limit(limit)
        )
        return [dict(row) for row in (await self._session.execute(query)).mappings()]

    async def get_assignment(
        self, branch_id: UUID, assignment_id: UUID
    ) -> StaffAssignmentData | None:
        row = await self._session.execute(
            select(
                StaffAssignmentModel,
                RoleModel.code,
                UserModel.first_name,
                UserModel.last_name,
                UserModel.email,
                UserModel.phone,
                UserModel.account_status,
            )
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
            .where(
                StaffAssignmentModel.id == assignment_id,
                StaffAssignmentModel.branch_id == branch_id,
            )
            .with_for_update(of=StaffAssignmentModel)
            .execution_options(populate_existing=True)
        )
        result = row.one_or_none()
        return (
            None
            if result is None
            else replace(
                self._staff_data(result[0], result[1]),
                first_name=result[2],
                last_name=result[3],
                email=result[4],
                phone=result[5],
                account_status=result[6],
            )
        )

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
        return await self.get_assignment(branch_id, model.id)

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
        return await self.get_assignment(assignment.branch_id, model.id)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
