from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.kitchen.application.services import KitchenService
from app.modules.kitchen.infrastructure.authorization import (
    SQLAlchemyKitchenAuthorization,
)
from app.modules.kitchen.infrastructure.orders import SQLAlchemyKitchenOrdersGateway
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_kitchen_service(session: SessionDependency) -> KitchenService:
    return KitchenService(
        SQLAlchemyKitchenOrdersGateway(session), SQLAlchemyKitchenAuthorization(session)
    )


KitchenServiceDependency = Annotated[KitchenService, Depends(get_kitchen_service)]
