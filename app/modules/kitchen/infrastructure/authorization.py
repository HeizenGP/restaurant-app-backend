from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)


class SQLAlchemyKitchenAuthorization:
    def __init__(self, session: AsyncSession) -> None:
        self._branches = SQLAlchemyBranchRepository(session)

    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission: str
    ) -> bool:
        return await self._branches.has_permission(user_id, branch_id, permission)
