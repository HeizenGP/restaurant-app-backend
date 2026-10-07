import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.auth.application.repository import CustomerIdentityData, UserData
from app.modules.auth.application.services import AuthService
from app.modules.auth.domain.models import Principal, PrincipalType
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
from app.modules.orders.presentation.dependencies import (
    get_order_service,
    get_order_settings_service,
)
from app.shared.domain.time import utc_now
from app.shared.infrastructure.config.settings import Settings
from tests.modules.auth.fakes import MemoryAuthRepository
from tests.modules.orders.fakes import OrdersSetup, orders_setup


@pytest.fixture
def setup():
    return asyncio.run(orders_setup())


@dataclass
class OrderApi:
    client: TestClient
    setup: OrdersSetup
    auth: MemoryAuthRepository
    tokens: dict[str, str] = field(repr=False)

    def headers(self, who="guest", key="order-test-1"):
        return {"Authorization": "Bearer " + self.tokens[who], "Idempotency-Key": key}

    def local_body(self, **values):
        return {
            "mode": "LOCAL",
            "table_qr_token": str(self.setup.table.qr_token),
            "payment_method": "CASH",
        } | values

    def create(self, who="guest", key="order-test-1", body=None):
        return self.client.post(
            "/api/v1/orders",
            headers=self.headers(who, key),
            json=body or self.local_body(),
        )

    @property
    def admin_path(self):
        return "/api/v1/admin/orders/branches/" + str(self.setup.cart.branch)


@pytest.fixture
def api(setup) -> Iterator[OrderApi]:
    auth = MemoryAuthRepository()
    tokens_service = PyJwtTokenService(
        secret="orders-tests-only-signing-key-at-least-32-characters",
        algorithm="HS256",
        issuer="orders-tests",
        audience="orders-tests",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=1),
        phone_verification_ttl=timedelta(minutes=5),
    )
    hasher = PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    dummy = hasher.hash_password("orders-tests-only-dummy")
    tokens = {}
    for index, (who, principal) in enumerate(
        (
            ("guest", setup.cart.guest),
            ("registered", setup.cart.registered),
            ("admin", setup.cart.admin),
            (
                "other",
                Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4()),
            ),
            (
                "staff",
                Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4()),
            ),
            (
                "foreign_admin",
                Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4()),
            ),
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
                phone="+5199999910" + str(index),
                email=None,
                phone_verified_at=utc_now(),
            )
        tokens[who] = tokens_service.create_access_token(principal)
    asyncio.run(auth.commit())
    auth_service = AuthService(
        repository=auth,
        password_hasher=hasher,
        token_service=tokens_service,
        refresh_token_hasher=Sha256RefreshTokenHasher(),
        otp_codes=HmacOtpCodeService(pepper="orders-tests-only-pepper"),
        otp_sender=InMemoryOtpSender(environment="test"),
        dummy_password_hash=dummy,
        access_expires_seconds=900,
        otp_expires=timedelta(minutes=5),
        otp_max_attempts=3,
        otp_resend_cooldown=timedelta(seconds=60),
        expose_debug_otp=True,
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_order_service] = lambda: setup.service
    app.dependency_overrides[get_order_settings_service] = lambda: setup.admin_service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield OrderApi(client, setup, auth, tokens)
