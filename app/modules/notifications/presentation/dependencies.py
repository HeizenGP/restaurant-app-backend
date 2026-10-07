from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.presentation.dependencies import get_auth_service
from app.modules.notifications.application.push import PushDispatchService
from app.modules.notifications.application.realtime import RealtimeStreamService
from app.modules.notifications.application.services import NotificationService
from app.modules.notifications.infrastructure.authorization import (
    SQLAlchemyNotificationAuthorization,
)
from app.modules.notifications.infrastructure.persistence.push import (
    SQLAlchemyPushRepository,
)
from app.modules.notifications.infrastructure.persistence.repositories import (
    SQLAlchemyNotificationRepository,
)
from app.modules.notifications.infrastructure.push_gateway import (
    ConfiguredPushGatewayRegistry,
)
from app.modules.notifications.infrastructure.realtime import SQLAlchemyStreamReader
from app.shared.infrastructure.database.dependencies import get_session

SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_push_registry():
    # No real mobile provider is configured in this phase.
    return ConfiguredPushGatewayRegistry()


RegistryDependency = Annotated[
    ConfiguredPushGatewayRegistry, Depends(get_push_registry)
]


def get_notification_service(session: SessionDependency, registry: RegistryDependency):
    return NotificationService(
        SQLAlchemyNotificationRepository(session),
        SQLAlchemyNotificationAuthorization(session),
        registry,
    )


def get_stream_service(request: Request):
    async def resolve_identity(session, token):
        return await get_auth_service(request, session).resolve_principal(token)

    return RealtimeStreamService(
        SQLAlchemyStreamReader(
            request.app.state.session_factory,
            resolve_identity,
            request.app.state.token_service.decode_access_token,
        )
    )


def get_push_dispatch_service(request: Request, registry: RegistryDependency):
    # Composition seam for a future external worker; intentionally no HTTP action.
    return PushDispatchService(
        SQLAlchemyPushRepository(request.app.state.session_factory), registry
    )


NotificationServiceDependency = Annotated[
    NotificationService, Depends(get_notification_service)
]
StreamServiceDependency = Annotated[RealtimeStreamService, Depends(get_stream_service)]
