from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.modules.admin.application.services import AdministrationReadService
from app.modules.admin.infrastructure.read_repository import (
    SQLAlchemyAdministrationReadRepository,
)
from app.modules.admin.presentation.schemas import (
    ConfigurationResponse,
    DashboardQuery,
    DashboardResponse,
)
from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    SessionDependency,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.presentation.errors import ErrorResponse
from app.shared.domain.time import utc_now

router = APIRouter(
    prefix="/admin",
    tags=["admin dashboard"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)


def get_administration_read_service(
    session: SessionDependency,
) -> AdministrationReadService:
    return AdministrationReadService(
        SQLAlchemyBranchRepository(session),
        SQLAlchemyAdministrationReadRepository(session),
    )


Service = Annotated[AdministrationReadService, Depends(get_administration_read_service)]


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    principal: CurrentRegisteredUser,
    service: Service,
    query: Annotated[DashboardQuery, Query()],
):
    return await service.dashboard(principal, now=utc_now(), **query.model_dump())


@router.get("/branches/{branch_id}/configuration", response_model=ConfigurationResponse)
async def configuration(
    branch_id: UUID, principal: CurrentRegisteredUser, service: Service
):
    return await service.configuration(principal, branch_id)
