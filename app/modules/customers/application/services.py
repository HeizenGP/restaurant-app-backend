import re
import unicodedata
from decimal import Decimal
from typing import TypeVar
from uuid import UUID

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
from app.modules.customers.application.ports import (
    CustomerRepository,
    CustomerUnitOfWorkFactory,
)

PHONE_PATTERN = re.compile(r"^\+?[0-9]{9,15}$")
T = TypeVar("T")
REGISTERED_PROFILE_FIELDS = frozenset({"first_name", "last_name", "email"})
GUEST_PROFILE_FIELDS = frozenset({"full_name"})
ADDRESS_MAX_LENGTHS = {
    "label": 80,
    "recipient_name": 180,
    "address_line": 500,
    "district": 120,
    "city": 120,
    "department": 120,
}
ADDRESS_REQUIRED_FIELDS = frozenset(
    {
        "label",
        "recipient_name",
        "recipient_phone",
        "address_line",
        "district",
        "city",
        "department",
    }
)


class CustomerService:
    def __init__(self, unit_of_work_factory: CustomerUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_profile(self, principal: Principal) -> CustomerProfile:
        customer_id, user_id = _principal_identity(principal)
        async with self._unit_of_work_factory() as unit_of_work:
            return await _require_profile(unit_of_work.customers, customer_id, user_id)

    async def update_profile(
        self, principal: Principal, update: ProfileUpdate
    ) -> CustomerProfile:
        customer_id, user_id = _principal_identity(principal)
        _validate_profile_update(principal, update)
        async with self._unit_of_work_factory() as unit_of_work:
            await _require_profile(unit_of_work.customers, customer_id, user_id)
            if principal.principal_type is PrincipalType.GUEST:
                profile = await unit_of_work.customers.update_guest_profile(
                    customer_id, full_name=_required(update.full_name)
                )
            else:
                registered_user_id = _required(user_id)
                if (
                    "email" in update.provided_fields
                    and update.email is not None
                    and await unit_of_work.customers.email_is_registered(
                        update.email, excluding=registered_user_id
                    )
                ):
                    raise EmailAlreadyRegisteredError
                profile = await unit_of_work.customers.update_registered_profile(
                    customer_id, registered_user_id, update
                )
            if profile is None:
                raise CustomerNotFoundError
            await unit_of_work.commit()
            return profile

    async def list_addresses(self, principal: Principal) -> list[Address]:
        customer_id, user_id = _principal_identity(principal)
        async with self._unit_of_work_factory() as unit_of_work:
            await _require_profile(unit_of_work.customers, customer_id, user_id)
            addresses = await unit_of_work.customers.list_addresses(customer_id)
            return list(addresses)

    async def create_address(
        self, principal: Principal, address: AddressCreate
    ) -> Address:
        _validate_address_create(address)
        customer_id, user_id = _principal_identity(principal)
        async with self._unit_of_work_factory() as unit_of_work:
            await _require_profile(unit_of_work.customers, customer_id, user_id)
            if address.is_default:
                await unit_of_work.customers.unset_default_address(customer_id)
            created = await unit_of_work.customers.create_address(customer_id, address)
            await unit_of_work.commit()
            return created

    async def update_address(
        self,
        principal: Principal,
        address_id: UUID,
        update: AddressUpdate,
    ) -> Address:
        _validate_address_update(update)
        customer_id, user_id = _principal_identity(principal)
        async with self._unit_of_work_factory() as unit_of_work:
            await _require_profile(unit_of_work.customers, customer_id, user_id)
            if update.is_default is True:
                await unit_of_work.customers.unset_default_address(
                    customer_id, keeping=address_id
                )
            address = await unit_of_work.customers.update_address(
                customer_id, address_id, update
            )
            if address is None:
                raise AddressNotFoundError
            await unit_of_work.commit()
            return address

    async def delete_address(self, principal: Principal, address_id: UUID) -> None:
        customer_id, user_id = _principal_identity(principal)
        async with self._unit_of_work_factory() as unit_of_work:
            await _require_profile(unit_of_work.customers, customer_id, user_id)
            if not await unit_of_work.customers.delete_address(customer_id, address_id):
                raise AddressNotFoundError
            await unit_of_work.commit()


async def _require_profile(
    repository: CustomerRepository, customer_id: UUID, user_id: UUID | None
) -> CustomerProfile:
    profile = await repository.get_profile(customer_id, user_id=user_id)
    if profile is None:
        raise CustomerNotFoundError
    return profile


def _principal_identity(principal: Principal) -> tuple[UUID, UUID | None]:
    if principal.customer_id is None:
        raise CustomerNotFoundError
    if (
        principal.principal_type is PrincipalType.REGISTERED
        and principal.user_id is None
    ):
        raise CustomerNotFoundError
    return principal.customer_id, principal.user_id


def _validate_profile_update(principal: Principal, update: ProfileUpdate) -> None:
    allowed = (
        GUEST_PROFILE_FIELDS
        if principal.principal_type is PrincipalType.GUEST
        else REGISTERED_PROFILE_FIELDS
    )
    if not update.provided_fields or not update.provided_fields <= allowed:
        raise InvalidCustomerDataError
    if "full_name" in update.provided_fields:
        _validate_text(update.full_name, maximum=180)
    if "first_name" in update.provided_fields:
        _validate_text(update.first_name, maximum=100)
    if "last_name" in update.provided_fields and update.last_name is not None:
        _validate_text(update.last_name, maximum=120)
    if "email" in update.provided_fields and update.email is not None:
        email = update.email
        if (
            len(email) > 254
            or email.count("@") != 1
            or any(character.isspace() for character in email)
            or _has_control_characters(email)
        ):
            raise InvalidCustomerDataError
        local_part, domain = email.rsplit("@", 1)
        if not local_part or not domain:
            raise InvalidCustomerDataError


def _validate_address_create(address: AddressCreate) -> None:
    for field, maximum in ADDRESS_MAX_LENGTHS.items():
        _validate_text(getattr(address, field), maximum=maximum)
    if not PHONE_PATTERN.fullmatch(address.recipient_phone):
        raise InvalidCustomerDataError
    if address.reference_text is not None:
        _validate_text(address.reference_text, maximum=500)
    _validate_coordinates(address.latitude, address.longitude)


def _validate_address_update(update: AddressUpdate) -> None:
    if not update.provided_fields:
        raise InvalidCustomerDataError
    for field in update.provided_fields & ADDRESS_REQUIRED_FIELDS:
        value = getattr(update, field)
        if field == "recipient_phone":
            if value is None or not PHONE_PATTERN.fullmatch(value):
                raise InvalidCustomerDataError
        else:
            _validate_text(value, maximum=ADDRESS_MAX_LENGTHS[field])
    if "reference_text" in update.provided_fields and update.reference_text is not None:
        _validate_text(update.reference_text, maximum=500)
    _validate_coordinates(update.latitude, update.longitude)


def _validate_text(value: str | None, *, maximum: int) -> None:
    if (
        value is None
        or not value.strip()
        or len(value) > maximum
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise InvalidCustomerDataError


def _validate_coordinates(latitude: Decimal | None, longitude: Decimal | None) -> None:
    if latitude is not None and (
        not latitude.is_finite() or not Decimal("-90") <= latitude <= Decimal("90")
    ):
        raise InvalidCustomerDataError
    if longitude is not None and (
        not longitude.is_finite() or not Decimal("-180") <= longitude <= Decimal("180")
    ):
        raise InvalidCustomerDataError


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character).startswith("C") for character in value)


def _required(value: T | None) -> T:
    if value is None:
        raise InvalidCustomerDataError
    return value
