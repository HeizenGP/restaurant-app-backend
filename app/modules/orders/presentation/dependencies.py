from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import get_current_customer
from app.modules.catalog.presentation.dependencies import CatalogServiceDependency
from app.modules.orders.application.services import OrderService, OrderSettingsService
from app.modules.orders.infrastructure.authorization import SQLAlchemyOrderAuthorization
from app.modules.orders.infrastructure.cart import SQLAlchemyCartCheckoutGateway
from app.modules.orders.infrastructure.customers import (
    SQLAlchemyCustomerCheckoutGateway,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyOrderSettingsRepository,
)
from app.modules.orders.infrastructure.scheduling import SQLAlchemyKitchenLoadEstimator
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]


def get_order_service(
    session: SessionDependency, catalog: CatalogServiceDependency
) -> OrderService:
    repository = SQLAlchemyOrderRepository(session)
    return OrderService(
        repository=repository,
        checkout=SQLAlchemyCartCheckoutGateway(session, catalog),
        customers=SQLAlchemyCustomerCheckoutGateway(session),
        settings=SQLAlchemyOrderSettingsRepository(session),
        estimator=SQLAlchemyKitchenLoadEstimator(repository),
        authorization=SQLAlchemyOrderAuthorization(session),
    )


def get_order_settings_service(session: SessionDependency) -> OrderSettingsService:
    return OrderSettingsService(
        SQLAlchemyOrderSettingsRepository(session),
        SQLAlchemyOrderAuthorization(session),
    )


OrderServiceDependency = Annotated[OrderService, Depends(get_order_service)]
OrderSettingsServiceDependency = Annotated[
    OrderSettingsService, Depends(get_order_settings_service)
]
