"""Public Orders-owned gateway; writes reuse the official settings repository."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.domain.models import BranchOrderSettings
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderSettingsRepository,
)


class SQLAlchemyBranchOrderConfiguration:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = SQLAlchemyOrderSettingsRepository(session)

    async def initialize(self, branch_id: UUID, timezone: str) -> None:
        await self.settings.save_settings(
            BranchOrderSettings(branch_id=branch_id, timezone=timezone)
        )

    async def synchronize_timezone(self, branch_id: UUID, timezone: str) -> None:
        current = await self.settings.get_settings(
            branch_id, lock=True, for_update=True
        )
        await self.settings.save_settings(replace(current, timezone=timezone))

    async def has_active_operations(self, branch_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                text("SELECT restaurant_phase10_branch_busy(:branch)"),
                {"branch": branch_id},
            )
        )
