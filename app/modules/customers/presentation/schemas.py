import unicodedata
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SafeFirstName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
SafeLastName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
SafeFullName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
]
SafeLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
SafeAddressLine = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
SafeLocation = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
SafeReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
Phone = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^\+?[0-9]{9,15}$")
]
Email = Annotated[EmailStr, Field(max_length=254)]
Latitude = Annotated[Decimal, Field(ge=-90, le=90, max_digits=9, decimal_places=6)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180, max_digits=10, decimal_places=7)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def reject_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(
            unicodedata.category(character).startswith("C") for character in value
        ):
            raise ValueError("control characters are not allowed")
        return value


class ProfileUpdateRequest(RequestModel):
    first_name: SafeFirstName | None = None
    last_name: SafeLastName | None = None
    email: Email | None = None
    full_name: SafeFullName | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for field in {"first_name", "full_name"} & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class CustomerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    first_name: str | None
    last_name: str | None
    email: EmailStr | None
    phone: str
    phone_verified: bool
    is_guest: bool


class AddressFields(RequestModel):
    label: SafeLabel
    recipient_name: SafeFullName
    recipient_phone: Phone
    address_line: SafeAddressLine
    reference_text: SafeReference | None = None
    district: SafeLocation
    city: SafeLocation = "Tarapoto"
    department: SafeLocation = "San Martín"
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    is_default: bool = False


class AddressCreateRequest(AddressFields):
    pass


class AddressUpdateRequest(RequestModel):
    label: SafeLabel | None = None
    recipient_name: SafeFullName | None = None
    recipient_phone: Phone | None = None
    address_line: SafeAddressLine | None = None
    reference_text: SafeReference | None = None
    district: SafeLocation | None = None
    city: SafeLocation | None = None
    department: SafeLocation | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    is_default: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        nullable = {"reference_text", "latitude", "longitude"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    recipient_name: str
    recipient_phone: str
    address_line: str
    reference_text: str | None
    district: str
    city: str
    department: str
    latitude: Decimal | None
    longitude: Decimal | None
    is_default: bool
