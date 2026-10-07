from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)


class SQLAlchemyFulfillmentAuthorization:
    def __init__(self, session: AsyncSession):
        self.branches = SQLAlchemyBranchRepository(session)

    async def has_permission(self, user_id, branch_id, permission):
        return await self.branches.has_permission(user_id, branch_id, permission)

    async def staff_is_active(self, user_id, branch_id, now):
        return await self.branches.staff_is_active(user_id, branch_id, now)
