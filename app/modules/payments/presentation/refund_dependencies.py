from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.application.refund_ports import OnlineRefundGateway
from app.modules.payments.application.refund_services import RefundService
from app.modules.payments.infrastructure.authorization import (
    SQLAlchemyPaymentAuthorization,
)
from app.modules.payments.infrastructure.persistence.refund_repositories import (
    SQLAlchemyRefundRepository,
)
from app.modules.payments.infrastructure.refund_gateway import (
    UnconfiguredOnlineRefundGateway,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_refund_gateway() -> OnlineRefundGateway:
    return UnconfiguredOnlineRefundGateway()


GatewayDependency = Annotated[OnlineRefundGateway, Depends(get_refund_gateway)]


def get_refund_service(session: SessionDependency, gateway: GatewayDependency):
    return RefundService(
        SQLAlchemyRefundRepository(session),
        SQLAlchemyPaymentAuthorization(session),
        gateway,
        SQLAlchemyAuditRecorder(session),
    )


RefundServiceDependency = Annotated[RefundService, Depends(get_refund_service)]
