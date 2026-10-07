from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import get_current_customer
from app.modules.cart.application.services import CartService
from app.modules.cart.infrastructure.catalog import CatalogSelectionAdapter
from app.modules.cart.infrastructure.persistence.repositories import (
    SQLAlchemyCartRepository,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.modules.catalog.presentation.dependencies import CatalogServiceDependency
from app.shared.infrastructure.database.dependencies import get_session

CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]


def get_cart_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    catalog: CatalogServiceDependency,
) -> CartService:
    return CartService(
        SQLAlchemyCartRepository(session),
        CatalogSelectionAdapter(catalog, SQLAlchemyCatalogRepository(session)),
    )


CartServiceDependency = Annotated[CartService, Depends(get_cart_service)]
