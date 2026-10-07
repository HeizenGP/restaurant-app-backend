from typing import Protocol

from app.modules.admin.domain.periods import BranchPeriod


class AdministrationReadRepository(Protocol):
    async def dashboard(self, periods: tuple[BranchPeriod, ...]) -> dict: ...
    async def configuration(self, branch_id) -> dict: ...
