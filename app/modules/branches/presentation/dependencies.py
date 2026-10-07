from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import get_current_principal
from app.modules.branches.application.services import BranchService
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def get_branch_service(session: SessionDependency) -> BranchService:
    return BranchService(
        SQLAlchemyBranchRepository(session), SQLAlchemyAuditRecorder(session)
    )


BranchServiceDependency = Annotated[BranchService, Depends(get_branch_service)]
