from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fulfillment.application.services import FulfillmentService
from app.modules.fulfillment.infrastructure.authorization import (
    SQLAlchemyFulfillmentAuthorization,
)
from app.modules.fulfillment.infrastructure.orders import (
    SQLAlchemyFulfillmentOrdersGateway,
)
from app.modules.fulfillment.infrastructure.persistence.repositories import (
    SQLAlchemyFulfillmentRepository,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_fulfillment_service(session: SessionDependency) -> FulfillmentService:
    return FulfillmentService(
        SQLAlchemyFulfillmentRepository(session),
        SQLAlchemyFulfillmentOrdersGateway(session),
        SQLAlchemyFulfillmentAuthorization(session),
        SQLAlchemyAuditRecorder(session),
    )


FulfillmentServiceDependency = Annotated[
    FulfillmentService, Depends(get_fulfillment_service)
]
