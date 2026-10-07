from datetime import date, datetime
from uuid import UUID

from app.modules.admin.application.ports import AdministrationReadRepository
from app.modules.admin.domain.periods import InvalidDashboardPeriod, branch_period
from app.modules.auth.domain.models import Principal
from app.shared.application.administration import (
    AdministrationAuthorization,
    AdministrationInvalid,
    AdminPermissionDenied,
    administrative_actor,
    require_administration,
)


class AdministrationReadService:
    def __init__(
        self,
        authorization: AdministrationAuthorization,
        repository: AdministrationReadRepository,
    ) -> None:
        self.authorization = authorization
        self.repository = repository

    async def dashboard(
        self,
        principal: Principal,
        *,
        now: datetime,
        branch_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> dict:
        actor = administrative_actor(principal)
        scopes = await self.authorization.authorized_branches(
            actor, "DASHBOARD_VIEW", branch_id=branch_id
        )
        if branch_id is not None:
            scopes = tuple(branch for branch in scopes if branch.id == branch_id)
        if not scopes:
            raise AdminPermissionDenied()
        if len(scopes) > 100:
            raise AdministrationInvalid(
                "DASHBOARD_INVALID_PERIOD",
                "Select a branch when scope exceeds 100 branches",
            )
        try:
            periods = tuple(
                branch_period(b.id, b.name, b.timezone, now, from_date, to_date)
                for b in scopes
            )
        except InvalidDashboardPeriod as exc:
            raise AdministrationInvalid("DASHBOARD_INVALID_PERIOD", str(exc)) from None
        return await self.repository.dashboard(periods)

    async def configuration(self, principal: Principal, branch_id: UUID) -> dict:
        await require_administration(
            self.authorization, principal, branch_id, "BRANCH_VIEW"
        )
        return await self.repository.configuration(branch_id)
