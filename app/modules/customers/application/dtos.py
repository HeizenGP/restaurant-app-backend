from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    id: UUID
    full_name: str
    phone: str
    email: str | None
    phone_verified: bool
    is_guest: bool
    first_name: str | None = None
    last_name: str | None = None


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    provided_fields: frozenset[str]
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    full_name: str | None = None


@dataclass(frozen=True, slots=True)
class Address:
    id: UUID
    label: str
    recipient_name: str
    recipient_phone: str
    address_line: str
    district: str
    city: str
    department: str
    is_default: bool
    reference_text: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AddressCreate:
    label: str
    recipient_name: str
    recipient_phone: str
    address_line: str
    district: str
    city: str
    department: str
    reference_text: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class AddressUpdate:
    provided_fields: frozenset[str]
    label: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    address_line: str | None = None
    reference_text: str | None = None
    district: str | None = None
    city: str | None = None
    department: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    is_default: bool | None = None
