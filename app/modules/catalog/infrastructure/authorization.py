from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.infrastructure.persistence.models import (
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    UserModel,
)
from app.modules.branches.infrastructure.persistence.models import (
    BranchModel,
    StaffAssignmentModel,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)

CATALOG_MANAGE = "CATALOG_MANAGE"


class SQLAlchemyCatalogAuthorization:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._branches = SQLAlchemyBranchRepository(session)

    async def can_manage(self, user_id: UUID, branch_id: UUID | None) -> bool:
        if branch_id is not None:
            return await self._branches.has_permission(
                user_id, branch_id, CATALOG_MANAGE
            )
        query = (
            select(StaffAssignmentModel.id)
            .join(UserModel, UserModel.id == StaffAssignmentModel.user_id)
            .join(BranchModel, BranchModel.id == StaffAssignmentModel.branch_id)
            .join(RoleModel, RoleModel.id == StaffAssignmentModel.role_id)
            .join(RolePermissionModel, RolePermissionModel.role_id == RoleModel.id)
            .join(
                PermissionModel, PermissionModel.id == RolePermissionModel.permission_id
            )
            .where(
                StaffAssignmentModel.user_id == user_id,
                StaffAssignmentModel.is_active.is_(True),
                StaffAssignmentModel.ended_at.is_(None),
                UserModel.account_status == "ACTIVE",
                UserModel.deleted_at.is_(None),
                BranchModel.is_active.is_(True),
                BranchModel.deleted_at.is_(None),
                RoleModel.code == "ADMIN",
                RoleModel.scope == "BRANCH",
                PermissionModel.code == CATALOG_MANAGE,
            )
            .limit(1)
        )
        return (await self._session.execute(query)).scalar_one_or_none() is not None
