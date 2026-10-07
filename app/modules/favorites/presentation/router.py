from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.presentation.dependencies import (
    CurrentPrincipal,
    SessionDependency,
)
from app.modules.catalog.presentation.dependencies import CatalogServiceDependency
from app.modules.catalog.presentation.schemas import PublicProductResponse
from app.modules.favorites.application.services import FavoriteService
from app.modules.favorites.infrastructure.catalog import CatalogFavoriteGateway
from app.modules.favorites.infrastructure.persistence.repositories import (
    SQLAlchemyFavoriteRepository,
)
from app.presentation.errors import ErrorResponse

router = APIRouter(
    prefix="/favorites",
    tags=["favorites"],
    responses={
        code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
    },
)


def get_favorite_service(session: SessionDependency, catalog: CatalogServiceDependency):
    return FavoriteService(
        SQLAlchemyFavoriteRepository(session), CatalogFavoriteGateway(session, catalog)
    )


Service = Annotated[FavoriteService, Depends(get_favorite_service)]


class FavoriteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: UUID
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class FavoriteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    created_at: datetime


class FavoriteProductResponse(FavoriteResponse):
    product: PublicProductResponse


@router.get("", response_model=list[FavoriteProductResponse])
async def list_favorites(
    principal: CurrentPrincipal,
    service: Service,
    query: Annotated[FavoriteQuery, Query()],
):
    return await service.list(principal, **query.model_dump())


@router.put("/{product_id}", response_model=FavoriteResponse)
async def add_favorite(product_id: UUID, principal: CurrentPrincipal, service: Service):
    return await service.add(principal, product_id)


@router.delete("/{product_id}", status_code=204)
async def remove_favorite(
    product_id: UUID, principal: CurrentPrincipal, service: Service
):
    await service.remove(principal, product_id)
    return Response(status_code=204)
