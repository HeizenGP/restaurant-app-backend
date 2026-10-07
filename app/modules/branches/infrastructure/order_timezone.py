"""Branches-owned timezone writer, enlisted in the caller's transaction."""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.models import BranchModel


class SQLAlchemyBranchTimezoneSynchronization:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def synchronize_timezone(self, branch_id: UUID, timezone: str) -> None:
        await self.session.execute(
            update(BranchModel)
            .where(BranchModel.id == branch_id)
            .values(timezone=timezone)
        )
