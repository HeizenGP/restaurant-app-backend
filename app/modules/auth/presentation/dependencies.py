from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.errors import (
    AuthDataUnavailableError,
    RegisteredUserRequiredError,
)
from app.modules.auth.application.services import AuthService
from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.auth.infrastructure.persistence.repositories import (
    SQLAlchemyAuthRepository,
)
from app.shared.infrastructure.database.dependencies import get_session

bearer_scheme = HTTPBearer(auto_error=False)
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_auth_service(request: Request, session: SessionDependency) -> AuthService:
    settings = request.app.state.settings
    return AuthService(
        repository=SQLAlchemyAuthRepository(session),
        password_hasher=request.app.state.password_hasher,
        token_service=request.app.state.token_service,
        refresh_token_hasher=request.app.state.refresh_token_hasher,
        otp_codes=request.app.state.otp_code_service,
        otp_sender=request.app.state.otp_sender,
        dummy_password_hash=request.app.state.dummy_password_hash,
        access_expires_seconds=settings.access_token_expire_minutes * 60,
        otp_expires=timedelta(minutes=settings.otp_expire_minutes),
        otp_max_attempts=settings.otp_max_attempts,
        otp_resend_cooldown=timedelta(seconds=settings.otp_resend_cooldown_seconds),
        expose_debug_otp=settings.otp_debug_expose_code,
    )


AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
BearerDependency = Annotated[
    HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
]


async def get_current_principal(
    credentials: BearerDependency, service: AuthServiceDependency
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthDataUnavailableError()
    return await service.resolve_principal(credentials.credentials)


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


async def get_current_registered_user(
    principal: CurrentPrincipal,
) -> Principal:
    if principal.principal_type is not PrincipalType.REGISTERED:
        raise RegisteredUserRequiredError()
    return principal


CurrentRegisteredUser = Annotated[Principal, Depends(get_current_registered_user)]


async def get_current_customer(principal: CurrentPrincipal) -> Principal:
    if principal.customer_id is None:
        raise AuthDataUnavailableError()
    return principal
