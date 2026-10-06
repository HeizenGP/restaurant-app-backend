from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import get_current_principal
from app.modules.customers.application.services import CustomerService
from app.modules.customers.infrastructure.persistence.repositories import (
    SQLAlchemyCustomerUnitOfWork,
)


def get_customer_service(request: Request) -> CustomerService:
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.session_factory
    )
    return CustomerService(lambda: SQLAlchemyCustomerUnitOfWork(session_factory))


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
CustomerServiceDependency = Annotated[CustomerService, Depends(get_customer_service)]
