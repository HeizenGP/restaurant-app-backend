import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.modules.auth.infrastructure.security.otp import HmacOtpCodeService
from app.modules.auth.infrastructure.security.otp_sender import InMemoryOtpSender
from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)
from app.modules.auth.infrastructure.security.refresh_tokens import (
    Sha256RefreshTokenHasher,
)
from app.modules.auth.infrastructure.security.tokens import PyJwtTokenService
from app.modules.health.application.services import HealthService
from app.modules.health.infrastructure.database import SQLAlchemyDatabaseProbe
from app.shared.infrastructure.database.engine import create_database_engine
from app.shared.infrastructure.database.session import create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = application.state.settings
    engine = create_database_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        password_hasher = PwdlibArgon2PasswordHasher()
        application.state.database_engine = engine
        application.state.session_factory = session_factory
        application.state.password_hasher = password_hasher
        application.state.dummy_password_hash = password_hasher.hash_password(
            "not-a-real-account-password"
        )
        application.state.token_service = PyJwtTokenService(
            secret=settings.jwt_secret.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            access_ttl=timedelta(minutes=settings.access_token_expire_minutes),
            refresh_ttl=timedelta(days=settings.refresh_token_expire_days),
            phone_verification_ttl=timedelta(
                minutes=settings.phone_verification_token_expire_minutes
            ),
        )
        application.state.refresh_token_hasher = Sha256RefreshTokenHasher()
        application.state.otp_code_service = HmacOtpCodeService(
            pepper=settings.otp_pepper.get_secret_value()
        )
        application.state.otp_sender = (
            InMemoryOtpSender(environment=settings.app_env)
            if settings.app_env in {"development", "test"}
            else None
        )
        application.state.health_service = HealthService(
            service=settings.app_name,
            version=settings.app_version,
            database=SQLAlchemyDatabaseProbe(
                session_factory, timeout=settings.database_timeout_seconds
            ),
        )
        logger.info("Backend started (environment=%s)", settings.app_env)
        yield
    finally:
        await engine.dispose()
        logger.info("Backend stopped; database pool disposed")
