import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.customers.application.dtos import (
    Address,
    AddressCreate,
    AddressUpdate,
    CustomerProfile,
    ProfileUpdate,
)
from app.modules.customers.application.exceptions import (
    AddressNotFoundError,
    CustomerNotFoundError,
    EmailAlreadyRegisteredError,
    InvalidCustomerDataError,
)
from app.modules.customers.application.services import CustomerService

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


def _address(*, default: bool = False) -> Address:
    return Address(
        id=ADDRESS_ID,
        label="Casa",
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


def _address_create(*, default: bool = False) -> AddressCreate:
    return AddressCreate(
        label="Casa",
        recipient_name="Ana Ruiz",
        recipient_phone="+51987654321",
        address_line="Jr. Lima 123",
        reference_text=None,
        district="Tarapoto",
        city="Tarapoto",
        department="San Martín",
        is_default=default,
    )


def _service_with_repository(
    profile: CustomerProfile | None = None,
) -> tuple[CustomerService, MagicMock, MagicMock, MagicMock]:
    repository = MagicMock()
    repository.get_profile = AsyncMock(return_value=profile or _profile())
    repository.email_is_registered = AsyncMock(return_value=False)
    repository.update_guest_profile = AsyncMock()
    repository.update_registered_profile = AsyncMock()
    repository.list_addresses = AsyncMock(return_value=[])
    repository.create_address = AsyncMock()
    repository.update_address = AsyncMock()
    repository.delete_address = AsyncMock()
    repository.unset_default_address = AsyncMock()

    unit_of_work = MagicMock()
    unit_of_work.customers = repository
    unit_of_work.__aenter__ = AsyncMock(return_value=unit_of_work)
    unit_of_work.__aexit__ = AsyncMock(return_value=None)
    unit_of_work.commit = AsyncMock()
    factory = MagicMock(return_value=unit_of_work)
    return CustomerService(factory), repository, unit_of_work, factory


def test_registered_profile_is_bound_to_both_principal_ids() -> None:
    profile = _profile()
    service, repository, _, _ = _service_with_repository(profile)

    result = asyncio.run(service.get_profile(_registered_principal()))

    assert result == profile
    repository.get_profile.assert_awaited_once_with(CUSTOMER_ID, user_id=USER_ID)


def test_guest_profile_update_changes_only_full_name() -> None:
    updated = _profile(guest=True, full_name="Ana María")
    service, repository, unit_of_work, _ = _service_with_repository(
        _profile(guest=True)
    )
    repository.update_guest_profile.return_value = updated
    profile_update = ProfileUpdate(
        provided_fields=frozenset({"full_name"}), full_name="Ana María"
    )

    result = asyncio.run(service.update_profile(_guest_principal(), profile_update))

    assert result == updated
    repository.update_guest_profile.assert_awaited_once_with(
        CUSTOMER_ID, full_name="Ana María"
    )
    repository.update_registered_profile.assert_not_awaited()
    unit_of_work.commit.assert_awaited_once_with()


def test_registered_profile_update_keeps_user_and_customer_atomic() -> None:
    updated = _profile(full_name="Elena Ruiz")
    service, repository, unit_of_work, _ = _service_with_repository()
    repository.update_registered_profile.return_value = updated
    profile_update = ProfileUpdate(
        provided_fields=frozenset({"first_name", "email"}),
        first_name="Elena",
        email="elena@example.com",
    )

    result = asyncio.run(
        service.update_profile(_registered_principal(), profile_update)
    )

    assert result == updated
    repository.email_is_registered.assert_awaited_once_with(
        "elena@example.com", excluding=USER_ID
    )
    repository.update_registered_profile.assert_awaited_once_with(
        CUSTOMER_ID, USER_ID, profile_update
    )
    unit_of_work.commit.assert_awaited_once_with()


def test_registered_profile_rejects_duplicate_email_safely() -> None:
    service, repository, unit_of_work, _ = _service_with_repository()
    repository.email_is_registered.return_value = True
    update = ProfileUpdate(
        provided_fields=frozenset({"email"}), email="used@example.com"
    )

    with pytest.raises(EmailAlreadyRegisteredError) as captured:
        asyncio.run(service.update_profile(_registered_principal(), update))

    assert captured.value.code == "EMAIL_ALREADY_REGISTERED"
    assert "used@example.com" not in captured.value.message
    repository.update_registered_profile.assert_not_awaited()
    unit_of_work.commit.assert_not_awaited()


def test_guest_cannot_update_registered_profile_fields() -> None:
    service, _, _, factory = _service_with_repository(_profile(guest=True))
    update = ProfileUpdate(
        provided_fields=frozenset({"email"}), email="guest@example.com"
    )

    with pytest.raises(InvalidCustomerDataError):
        asyncio.run(service.update_profile(_guest_principal(), update))

    factory.assert_not_called()


def test_promoted_customer_rejects_an_old_guest_principal() -> None:
    service, repository, _, _ = _service_with_repository()
    repository.get_profile.return_value = None

    with pytest.raises(CustomerNotFoundError):
        asyncio.run(service.list_addresses(_guest_principal()))

    repository.list_addresses.assert_not_awaited()


def test_listing_addresses_always_uses_principal_customer_id() -> None:
    expected = [_address()]
    service, repository, _, _ = _service_with_repository()
    repository.list_addresses.return_value = expected

    result = asyncio.run(service.list_addresses(_registered_principal()))

    assert result == expected
    repository.list_addresses.assert_awaited_once_with(CUSTOMER_ID)


def test_creating_default_address_unsets_previous_default_in_transaction() -> None:
    expected = _address(default=True)
    service, repository, unit_of_work, _ = _service_with_repository()
    repository.create_address.return_value = expected
    address_create = _address_create(default=True)

    result = asyncio.run(
        service.create_address(_registered_principal(), address_create)
    )

    assert result == expected
    repository.unset_default_address.assert_awaited_once_with(CUSTOMER_ID)
    repository.create_address.assert_awaited_once_with(CUSTOMER_ID, address_create)
    unit_of_work.commit.assert_awaited_once_with()


def test_updating_foreign_address_returns_safe_not_found() -> None:
    service, repository, unit_of_work, _ = _service_with_repository()
    repository.update_address.return_value = None
    update = AddressUpdate(
        provided_fields=frozenset({"label"}),
        label="Trabajo",
    )

    with pytest.raises(AddressNotFoundError) as captured:
        asyncio.run(service.update_address(_registered_principal(), uuid4(), update))

    assert captured.value.code == "ADDRESS_NOT_FOUND"
    unit_of_work.commit.assert_not_awaited()


def test_marking_address_default_unsets_only_other_addresses() -> None:
    service, repository, unit_of_work, _ = _service_with_repository()
    repository.update_address.return_value = _address(default=True)
    update = AddressUpdate(provided_fields=frozenset({"is_default"}), is_default=True)

    asyncio.run(service.update_address(_registered_principal(), ADDRESS_ID, update))

    repository.unset_default_address.assert_awaited_once_with(
        CUSTOMER_ID, keeping=ADDRESS_ID
    )
    unit_of_work.commit.assert_awaited_once_with()


def test_deleting_foreign_address_returns_safe_not_found() -> None:
    service, repository, unit_of_work, _ = _service_with_repository()
    repository.delete_address.return_value = False

    with pytest.raises(AddressNotFoundError):
        asyncio.run(service.delete_address(_guest_principal(), ADDRESS_ID))

    repository.delete_address.assert_awaited_once_with(CUSTOMER_ID, ADDRESS_ID)
    unit_of_work.commit.assert_not_awaited()
