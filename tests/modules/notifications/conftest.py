import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.auth.application.repository import CustomerIdentityData, UserData
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
from app.modules.auth.presentation.dependencies import get_auth_service
from app.modules.notifications.application.realtime import RealtimeStreamService
from app.modules.notifications.presentation.dependencies import (
    get_notification_service,
    get_stream_service,
)
from app.shared.domain.time import utc_now
from app.shared.infrastructure.config.settings import Settings
from tests.modules.auth.fakes import MemoryAuthRepository
from tests.modules.notifications.fakes import (
    Clock,
    MemoryStreamReader,
    notification_setup,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def setup():
    return notification_setup()


@dataclass
class NotificationApi:
    client: TestClient
    setup: object
    auth: object
    tokens: dict = field(repr=False)
    reader: object
    stream: object

    def headers(self, who="customer", **extra):
        return {"Authorization": "Bearer " + self.tokens[who]} | extra

    @property
    def base(self):
        return "/api/v1/notifications"

    @property
    def admin(self):
        return "/api/v1/admin/realtime/branches/" + str(self.setup.branch) + "/orders"

    @property
    def kitchen(self):
        return "/api/v1/kitchen/branches/" + str(self.setup.branch) + "/orders/stream"


@pytest.fixture
def api(setup):
    auth = MemoryAuthRepository()
    token_service = PyJwtTokenService(
        secret="notifications-tests-only-signing-key-at-least-32-characters",
        algorithm="HS256",
        issuer="notifications-tests",
        audience="notifications-tests",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=1),
        phone_verification_ttl=timedelta(minutes=5),
    )
    hasher = PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    dummy = hasher.hash_password("notifications-tests-only-dummy")
    tokens = {}
    for index, who in enumerate(("customer", "guest", "foreign", "admin", "kitchen")):
        p = getattr(setup, who)
        if p.user_id:
            auth.users[p.user_id] = UserData(
                id=p.user_id,
                phone=None,
                email=who + "@example.test",
                first_name="Test",
                last_name=None,
                password_hash=dummy,
                account_status="ACTIVE",
                phone_verified_at=None,
                deleted_at=None,
            )
        if p.customer_id:
            auth.customers[p.customer_id] = CustomerIdentityData(
                id=p.customer_id,
                user_id=p.user_id,
                full_name=who,
                phone="+5190000040" + str(index),
                email=None,
                phone_verified_at=utc_now(),
            )
        tokens[who] = token_service.create_access_token(p)
    asyncio.run(auth.commit())
    auth_service = AuthService(
        repository=auth,
        password_hasher=hasher,
        token_service=token_service,
        refresh_token_hasher=Sha256RefreshTokenHasher(),
        otp_codes=HmacOtpCodeService(pepper="notifications-tests-only-pepper"),
        otp_sender=InMemoryOtpSender(environment="test"),
        dummy_password_hash=dummy,
        access_expires_seconds=900,
        otp_expires=timedelta(minutes=5),
        otp_max_attempts=3,
        otp_resend_cooldown=timedelta(seconds=60),
        expose_debug_otp=True,
    )
    clock = Clock(utc_now())
    reader = MemoryStreamReader(
        setup.repo,
        resolve=auth_service.resolve_principal,
        decode=token_service.decode_access_token,
        clock=clock,
    )

    async def fast_test_sleep(seconds):
        # End test HTTP streams quickly without changing the production defaults.
        clock.advance(301)

    stream = RealtimeStreamService(
        reader, clock=clock, monotonic=clock.monotonic, sleep=fast_test_sleep
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_notification_service] = lambda: setup.service
    app.dependency_overrides[get_stream_service] = lambda: stream
    with TestClient(app, raise_server_exceptions=False) as client:
        yield NotificationApi(client, setup, auth, tokens, reader, stream)
