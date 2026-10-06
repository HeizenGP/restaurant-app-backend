from datetime import timedelta

import pytest

from app.modules.auth.application.services import AuthService
from app.modules.auth.infrastructure.security.otp import HmacOtpCodeService
from app.modules.auth.infrastructure.security.otp_sender import InMemoryOtpSender
from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)
from app.modules.auth.infrastructure.security.refresh_tokens import (
    Sha256RefreshTokenHasher,
)
from app.modules.auth.infrastructure.security.tokens import PyJwtTokenService
from tests.modules.auth.fakes import MemoryAuthRepository


@pytest.fixture
def repository() -> MemoryAuthRepository:
    return MemoryAuthRepository()


@pytest.fixture
def token_service() -> PyJwtTokenService:
    return PyJwtTokenService(
        secret="test-only-signing-key-with-at-least-32-characters",
        algorithm="HS256",
        issuer="tests",
        audience="tests",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=30),
        phone_verification_ttl=timedelta(minutes=10),
    )


@pytest.fixture
def password_hasher() -> PwdlibArgon2PasswordHasher:
    # Reduced cost only in tests; production retains the adapter defaults.
    return PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)


@pytest.fixture
def auth_service(
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
    password_hasher: PwdlibArgon2PasswordHasher,
) -> AuthService:
    return AuthService(
        repository=repository,
        password_hasher=password_hasher,
        token_service=token_service,
        refresh_token_hasher=Sha256RefreshTokenHasher(),
        otp_codes=HmacOtpCodeService(pepper="test-only-pepper"),
        otp_sender=InMemoryOtpSender(environment="test"),
        dummy_password_hash=password_hasher.hash_password("unused-dummy-password"),
        access_expires_seconds=900,
        otp_expires=timedelta(minutes=5),
        otp_max_attempts=3,
        otp_resend_cooldown=timedelta(seconds=60),
        expose_debug_otp=True,
    )
