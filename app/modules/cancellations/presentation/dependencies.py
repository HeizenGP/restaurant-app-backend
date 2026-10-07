from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cancellations.application.services import CancellationService
from app.modules.cancellations.infrastructure.authorization import (
    SQLAlchemyCancellationAuthorization,
)
from app.modules.cancellations.infrastructure.fulfillment import (
    SQLAlchemyCancellationFulfillmentGateway,
)
from app.modules.cancellations.infrastructure.orders import (
    SQLAlchemyCancellationOrdersGateway,
)
from app.modules.cancellations.infrastructure.payments import (
    SQLAlchemyCancellationRefundGateway,
)
from app.modules.cancellations.infrastructure.persistence.repositories import (
    SQLAlchemyCancellationRepository,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_cancellation_service(session: SessionDependency):
    return CancellationService(
        SQLAlchemyCancellationRepository(session),
        SQLAlchemyCancellationOrdersGateway(session),
        SQLAlchemyCancellationAuthorization(session),
        SQLAlchemyCancellationRefundGateway(session),
        SQLAlchemyCancellationFulfillmentGateway(session),
        SQLAlchemyAuditRecorder(session),
    )


CancellationServiceDependency = Annotated[
    CancellationService, Depends(get_cancellation_service)
]
