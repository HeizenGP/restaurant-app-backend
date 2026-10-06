from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.auth.presentation.dependencies import get_current_principal
from app.modules.customers.application.dtos import Address, CustomerProfile
from app.modules.customers.application.exceptions import (
    AddressNotFoundError,
    EmailAlreadyRegisteredError,
)
from app.modules.customers.application.services import CustomerService
from app.modules.customers.presentation.dependencies import get_customer_service
from app.modules.customers.presentation.router import router
from app.presentation.errors import register_exception_handlers

CUSTOMER_ID = UUID("10000000-0000-0000-0000-000000000001")
USER_ID = UUID("20000000-0000-0000-0000-000000000001")
ADDRESS_ID = UUID("30000000-0000-0000-0000-000000000001")


def _registered_principal() -> Principal:
    return Principal(
        principal_type=PrincipalType.REGISTERED,
        user_id=USER_ID,
        customer_id=CUSTOMER_ID,
    )


def _guest_principal() -> Principal:
    return Principal(
        principal_type=PrincipalType.GUEST,
        customer_id=CUSTOMER_ID,
    )


def _profile(*, guest: bool = False, full_name: str = "Ana Ruiz") -> CustomerProfile:
    return CustomerProfile(
        id=CUSTOMER_ID,
        full_name=full_name,
        first_name=None if guest else "Ana",
        last_name=None if guest else "Ruiz",
        email=None if guest else "ana@example.com",
        phone="+51987654321",
        phone_verified=True,
        is_guest=guest,
    )


def _address(*, default: bool = False, label: str = "Casa") -> Address:
    return Address(
        id=ADDRESS_ID,
        label=label,
        recipient_name="Ana Ruiz",
        recipient_phone="+51987654321",
        address_line="Jr. Lima 123",
        reference_text="Frente al parque",
        district="Tarapoto",
        city="Tarapoto",
        department="San Martín",
        latitude=None,
        longitude=None,
        is_default=default,
    )


def _service() -> MagicMock:
    service = MagicMock(spec=CustomerService)
    service.get_profile = AsyncMock()
    service.update_profile = AsyncMock()
    service.list_addresses = AsyncMock()
    service.create_address = AsyncMock()
    service.update_address = AsyncMock()
    service.delete_address = AsyncMock()
    return service


@contextmanager
def _client(service: MagicMock, principal: Principal) -> Iterator[TestClient]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(router, prefix="/api/v1")
    application.dependency_overrides[get_current_principal] = lambda: principal
    application.dependency_overrides[get_customer_service] = lambda: service
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


def test_get_registered_profile_does_not_expose_internal_fields() -> None:
    service = _service()
    service.get_profile.return_value = _profile()

    with _client(service, _registered_principal()) as client:
        response = client.get("/api/v1/customers/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(CUSTOMER_ID),
        "full_name": "Ana Ruiz",
        "first_name": "Ana",
        "last_name": "Ruiz",
        "email": "ana@example.com",
        "phone": "+51987654321",
        "phone_verified": True,
        "is_guest": False,
    }
    assert "user_id" not in response.text
    assert "account_status" not in response.text
    service.get_profile.assert_awaited_once_with(_registered_principal())


def test_guest_can_patch_only_safe_profile_fields() -> None:
    service = _service()
    service.update_profile.return_value = _profile(guest=True, full_name="Ana María")

    with _client(service, _guest_principal()) as client:
        response = client.patch(
            "/api/v1/customers/me", json={"full_name": "  Ana María  "}
        )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Ana María"
    principal, update = service.update_profile.await_args.args
    assert principal == _guest_principal()
    assert update.full_name == "Ana María"
    assert update.provided_fields == frozenset({"full_name"})


def test_profile_patch_never_accepts_phone() -> None:
    service = _service()

    with _client(service, _registered_principal()) as client:
        response = client.patch(
            "/api/v1/customers/me",
            json={"phone": "+51999999999"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "+51999999999" not in response.text
    service.update_profile.assert_not_awaited()


def test_duplicate_email_uses_safe_conflict_response() -> None:
    service = _service()
    service.update_profile.side_effect = EmailAlreadyRegisteredError()

    with _client(service, _registered_principal()) as client:
        response = client.patch(
            "/api/v1/customers/me",
            json={"email": "private@example.com"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "EMAIL_ALREADY_REGISTERED",
            "message": "Email is already registered",
        }
    }
    assert "private@example.com" not in response.text


def test_address_create_never_accepts_customer_id() -> None:
    service = _service()
    payload = {
        "customer_id": str(UUID("90000000-0000-0000-0000-000000000009")),
        "label": "Casa",
        "recipient_name": "Ana Ruiz",
        "recipient_phone": "+51987654321",
        "address_line": "Jr. Lima 123",
        "district": "Tarapoto",
    }

    with _client(service, _guest_principal()) as client:
        response = client.post("/api/v1/customers/me/addresses", json=payload)

    assert response.status_code == 422
    service.create_address.assert_not_awaited()


def test_create_and_list_addresses() -> None:
    service = _service()
    service.create_address.return_value = _address(default=True)
    service.list_addresses.return_value = [_address(default=True)]
    payload = {
        "label": "Casa",
        "recipient_name": "Ana Ruiz",
        "recipient_phone": "+51987654321",
        "address_line": "Jr. Lima 123",
        "district": "Tarapoto",
        "is_default": True,
    }

    with _client(service, _guest_principal()) as client:
        created = client.post("/api/v1/customers/me/addresses", json=payload)
        listed = client.get("/api/v1/customers/me/addresses")

    assert created.status_code == 201
    assert created.json()["id"] == str(ADDRESS_ID)
    assert created.json()["is_default"] is True
    assert listed.status_code == 200
    assert listed.json() == [created.json()]
    principal, address = service.create_address.await_args.args
    assert principal == _guest_principal()
    assert address.city == "Tarapoto"
    assert address.department == "San Martín"
    assert address.is_default is True


def test_patch_address_uses_path_id_and_principal() -> None:
    service = _service()
    service.update_address.return_value = _address(label="Trabajo")

    with _client(service, _registered_principal()) as client:
        response = client.patch(
            f"/api/v1/customers/me/addresses/{ADDRESS_ID}",
            json={"label": "Trabajo"},
        )

    assert response.status_code == 200
    principal, address_id, update = service.update_address.await_args.args
    assert principal == _registered_principal()
    assert address_id == ADDRESS_ID
    assert update.label == "Trabajo"
    assert update.provided_fields == frozenset({"label"})


def test_foreign_address_is_indistinguishable_from_missing() -> None:
    service = _service()
    service.update_address.side_effect = AddressNotFoundError()

    with _client(service, _guest_principal()) as client:
        response = client.patch(
            f"/api/v1/customers/me/addresses/{ADDRESS_ID}",
            json={"label": "Trabajo"},
        )

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "ADDRESS_NOT_FOUND", "message": "Address not found"}
    }


def test_delete_address_returns_no_content() -> None:
    service = _service()

    with _client(service, _registered_principal()) as client:
        response = client.delete(f"/api/v1/customers/me/addresses/{ADDRESS_ID}")

    assert response.status_code == 204
    assert response.content == b""
    service.delete_address.assert_awaited_once_with(_registered_principal(), ADDRESS_ID)
