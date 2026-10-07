import asyncio
from dataclasses import dataclass, field, replace
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
from app.modules.kitchen.presentation.dependencies import get_kitchen_service
from app.shared.domain.time import utc_now
from app.shared.infrastructure.config.settings import Settings
from tests.modules.auth.fakes import MemoryAuthRepository
from tests.modules.kitchen.fakes import KitchenSetup, kitchen_setup


@pytest.fixture
def setup():
    return kitchen_setup()


@dataclass
class KitchenApi:
    client: TestClient
    setup: KitchenSetup
    auth: MemoryAuthRepository
    tokens: dict[str, str] = field(repr=False)

    def headers(self, who="kitchen"):
        return {"Authorization": "Bearer " + self.tokens[who]}

    @property
    def base(self):
        return "/api/v1/kitchen/branches/" + str(self.setup.branch)

    @property
    def order_path(self):
        return self.base + "/orders/" + str(self.setup.row.id)


@pytest.fixture
def api(setup):
    auth = MemoryAuthRepository()
    tokens_service = PyJwtTokenService(
        secret="kitchen-tests-only-signing-key-at-least-32-characters",
        algorithm="HS256",
        issuer="kitchen-tests",
        audience="kitchen-tests",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=1),
        phone_verification_ttl=timedelta(minutes=5),
    )
    hasher = PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    dummy = hasher.hash_password("kitchen-tests-only-dummy")
    tokens = {}
    for index, (who, principal) in enumerate(
        (
            ("kitchen", setup.user),
            ("admin", setup.admin),
            ("customer", setup.customer),
            ("guest", setup.guest),
            ("foreign", setup.foreign),
        )
    ):
        if principal.user_id:
            auth.users[principal.user_id] = UserData(
                id=principal.user_id,
                phone=None,
                email=who + "@example.test",
                first_name="Test",
                last_name=None,
                password_hash=dummy,
                account_status="ACTIVE",
                phone_verified_at=None,
                deleted_at=None,
            )
        if principal.customer_id:
            auth.customers[principal.customer_id] = CustomerIdentityData(
                id=principal.customer_id,
                user_id=principal.user_id,
                full_name=who,
                phone="+5199999920" + str(index),
                email=None,
                phone_verified_at=utc_now(),
            )
        tokens[who] = tokens_service.create_access_token(principal)
    asyncio.run(auth.commit())
    service = AuthService(
        repository=auth,
        password_hasher=hasher,
        token_service=tokens_service,
        refresh_token_hasher=Sha256RefreshTokenHasher(),
        otp_codes=HmacOtpCodeService(pepper="kitchen-tests-only-pepper"),
        otp_sender=InMemoryOtpSender(environment="test"),
        dummy_password_hash=dummy,
        access_expires_seconds=900,
        otp_expires=timedelta(minutes=5),
        otp_max_attempts=3,
        otp_resend_cooldown=timedelta(seconds=60),
        expose_debug_otp=True,
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_kitchen_service] = lambda: setup.service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield KitchenApi(client, setup, auth, tokens)


def block_user(api, who):
    user_id = api.setup.user.user_id if who == "kitchen" else api.setup.admin.user_id
    api.auth.users[user_id] = replace(api.auth.users[user_id], account_status="BLOCKED")
