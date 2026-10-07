from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import get_current_customer
from app.modules.payments.application.ports import OnlinePaymentGateway
from app.modules.payments.application.services import PaymentService
from app.modules.payments.infrastructure.authorization import (
    SQLAlchemyPaymentAuthorization,
)
from app.modules.payments.infrastructure.gateway import UnconfiguredOnlinePaymentGateway
from app.modules.payments.infrastructure.orders import SQLAlchemyPaymentOrderLifecycle
from app.modules.payments.infrastructure.persistence.repositories import (
    SQLAlchemyPaymentRepository,
)
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]


def get_payment_gateway() -> OnlinePaymentGateway:
    """Replace this explicit adapter only after choosing/configuring a real provider."""
    return UnconfiguredOnlinePaymentGateway()


GatewayDependency = Annotated[OnlinePaymentGateway, Depends(get_payment_gateway)]


def get_payment_service(
    session: SessionDependency, gateway: GatewayDependency
) -> PaymentService:
    return PaymentService(
        SQLAlchemyPaymentRepository(session),
        SQLAlchemyPaymentOrderLifecycle(session),
        SQLAlchemyPaymentAuthorization(session),
        gateway,
    )


PaymentServiceDependency = Annotated[PaymentService, Depends(get_payment_service)]
