from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.infrastructure.authorization import (
    SQLAlchemyCatalogAuthorization,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from app.shared.infrastructure.database.dependencies import get_session


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogService:
    return CatalogService(
        SQLAlchemyCatalogRepository(session),
        SQLAlchemyCatalogAuthorization(session),
        SQLAlchemyAuditRecorder(session),
    )


CatalogServiceDependency = Annotated[CatalogService, Depends(get_catalog_service)]
