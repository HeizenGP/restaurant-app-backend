from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class CreateAdministrativeCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=1, max_length=180)
    phone: str = Field(pattern=r"^\+?[0-9]{9,15}$")
    email: EmailStr | None = None


class UpdateAdministrativeCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str | None = Field(default=None, min_length=1, max_length=180)
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(
            getattr(self, key) is None
            for key in self.model_fields_set - {"email", "last_name"}
        ):
            raise ValueError("Required names cannot be null")
        if "full_name" in self.model_fields_set and self.model_fields_set & {
            "first_name",
            "last_name",
        }:
            raise ValueError("Use either guest or registered name fields")
        return self


class CustomerSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    search: str | None = Field(default=None, min_length=2, max_length=80)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class AdministrativeCustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    full_name: str
    phone: str
    email: str | None
    is_guest: bool
    phone_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    first_name: str | None = None
    last_name: str | None = None
