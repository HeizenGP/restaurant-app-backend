from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.auth.application.services import AuthService
from app.modules.auth.presentation.dependencies import get_auth_service
from app.shared.infrastructure.config.settings import Settings
from tests.modules.auth.fakes import MemoryAuthRepository

PHONE = "+51987654321"
PASSWORD = "test-only-correct-password"


@pytest.fixture
def auth_client(auth_service: AuthService) -> Iterator[TestClient]:
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def proof(client: TestClient, purpose: str, phone: str = PHONE) -> str:
    requested = client.post(
        "/api/v1/auth/otp/request", json={"phone": phone, "purpose": purpose}
    )
    assert requested.status_code == 202
    response = client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": phone,
            "purpose": purpose,
            "code": requested.json()["debug_code"],
        },
    )
    assert response.status_code == 200
    return response.json()["verification_token"]


def register(client: TestClient) -> dict[str, str]:
    token = proof(client, "REGISTER")
    response = client.post(
        "/api/v1/auth/register",
        json={
            "verification_token": token,
            "first_name": "Ana",
            "last_name": "Ruiz",
            "email": "ana@example.com",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 201
    assert set(response.json()) == {
        "access_token",
        "refresh_token",
        "token_type",
        "expires_in",
    }
    return response.json()


def test_registration_login_refresh_logout_over_http(auth_client: TestClient) -> None:
    created = register(auth_client)
    login = auth_client.post(
        "/api/v1/auth/login", json={"identifier": PHONE, "password": PASSWORD}
    )
    assert login.status_code == 200
    refreshed = auth_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": created["refresh_token"]}
    )
    assert refreshed.status_code == 200
    reused = auth_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": created["refresh_token"]}
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "REFRESH_TOKEN_REVOKED"
    logout = auth_client.post(
        "/api/v1/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]}
    )
    assert logout.status_code == 204 and not logout.content
    assert (
        auth_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refreshed.json()["refresh_token"]},
        ).status_code
        == 401
    )


def test_guest_http_flow_promotes_customer_and_rejects_old_guest(
    auth_client: TestClient, repository: MemoryAuthRepository
) -> None:
    guest = auth_client.post(
        "/api/v1/auth/guest",
        json={
            "verification_token": proof(auth_client, "GUEST_ACCESS"),
            "full_name": "Ana",
        },
    )
    assert guest.status_code == 200
    assert "refresh_token" not in guest.json()
    customer_id = next(iter(repository.customers))
    register(auth_client)
    assert list(repository.customers) == [customer_id]
    rejected = auth_client.get(
        "/api/v1/customers/me",
        headers={"Authorization": f"Bearer {guest.json()['access_token']}"},
    )
    assert rejected.status_code == 401


@pytest.mark.parametrize(
    "field,value",
    [("phone", PHONE), ("roles", ["ADMIN"]), ("account_status", "ACTIVE")],
)
def test_register_rejects_mass_assignment(
    auth_client: TestClient, field: str, value: object
) -> None:
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "verification_token": "unused",
            "first_name": "Ana",
            "password": PASSWORD,
            field: value,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert PASSWORD not in response.text


def test_invalid_login_and_missing_account_are_indistinguishable(
    auth_client: TestClient,
) -> None:
    register(auth_client)
    wrong = auth_client.post(
        "/api/v1/auth/login", json={"identifier": PHONE, "password": "wrong"}
    )
    missing = auth_client.post(
        "/api/v1/auth/login",
        json={"identifier": "absent@example.com", "password": "wrong"},
    )
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json() == missing.json()
    assert wrong.headers["www-authenticate"] == "Bearer"


def test_change_password_revokes_sessions_over_http(auth_client: TestClient) -> None:
    pair = register(auth_client)
    changed = auth_client.post(
        "/api/v1/auth/password/change",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
        json={"current_password": PASSWORD, "new_password": "new test-only password"},
    )
    assert changed.status_code == 204
    assert (
        auth_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": pair["refresh_token"]}
        ).status_code
        == 401
    )
    assert (
        auth_client.post(
            "/api/v1/auth/login",
            json={"identifier": PHONE, "password": "new test-only password"},
        ).status_code
        == 200
    )


def test_change_phone_uses_verified_phone_and_syncs_user_customer(
    auth_client: TestClient, repository: MemoryAuthRepository
) -> None:
    pair = register(auth_client)
    verified = proof(auth_client, "PHONE_VERIFY", "+51911111111")
    response = auth_client.post(
        "/api/v1/auth/phone/change",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
        json={"verification_token": verified},
    )
    assert response.status_code == 204
    assert next(iter(repository.users.values())).phone == "+51911111111"
    assert next(iter(repository.customers.values())).phone == "+51911111111"


def test_blocked_account_is_checked_by_protected_dependencies(
    auth_client: TestClient, repository: MemoryAuthRepository
) -> None:
    pair = register(auth_client)
    user = next(iter(repository.users.values()))
    repository.users[user.id] = replace(user, account_status="BLOCKED")
    response = auth_client.get(
        "/api/v1/customers/me",
        headers={"Authorization": f"Bearer {pair['access_token']}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_BLOCKED"


@pytest.mark.parametrize("kind", ["refresh_token", "phone_verification"])
def test_non_access_tokens_are_rejected_as_authentication(
    auth_client: TestClient, kind: str
) -> None:
    pair = register(auth_client)
    token = (
        pair["refresh_token"]
        if kind == "refresh_token"
        else proof(auth_client, "PHONE_VERIFY", "+51911111111")
    )
    response = auth_client.get(
        "/api/v1/customers/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


def test_openapi_documents_real_error_envelope(auth_client: TestClient) -> None:
    schema = auth_client.get("/openapi.json").json()
    for path in ("/api/v1/auth/register", "/api/v1/branches/{branch_id}/staff"):
        response = schema["paths"][path]["post"]["responses"]["422"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith(
            "/ErrorResponse"
        )
