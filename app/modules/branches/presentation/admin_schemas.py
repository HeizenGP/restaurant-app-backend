from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Pagination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class CandidateQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    search: str = Field(min_length=2, max_length=80)
    limit: int = Field(default=20, ge=1, le=100)


class HourInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day_of_week: int = Field(ge=0, le=6, strict=True)
    open_time: time | None = None
    close_time: time | None = None
    is_closed: bool

    @model_validator(mode="after")
    def consistent(self):
        if self.is_closed:
            if self.open_time is not None or self.close_time is not None:
                raise ValueError("Closed days must not specify times")
        elif self.open_time is None or self.close_time is None:
            raise ValueError("Open days must specify both times")
        if any(
            t is not None and t.tzinfo is not None
            for t in (self.open_time, self.close_time)
        ):
            raise ValueError("Hours are local times without timezone")
        return self


class HoursInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: list[HourInput] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def complete(self):
        if {h.day_of_week for h in self.hours} != set(range(7)):
            raise ValueError("Provide every weekday exactly once")
        return self


class CreateBranchRequest(HoursInput):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    code: str = Field(
        min_length=1, max_length=40, pattern=r"^[A-Z0-9][A-Z0-9_-]{0,39}$"
    )
    name: str = Field(min_length=1, max_length=150)
    address_line: str = Field(min_length=1, max_length=1000)
    district: str = Field(min_length=1, max_length=120)
    city: str = Field(default="Tarapoto", min_length=1, max_length=120)
    department: str = Field(default="San Martín", min_length=1, max_length=120)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{9,15}$")
    timezone: str = Field(default="America/Lima", min_length=1, max_length=64)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class UpdateBranchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, allow_inf_nan=False
    )
    name: str | None = Field(default=None, min_length=1, max_length=150)
    address_line: str | None = Field(default=None, min_length=1, max_length=1000)
    district: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, min_length=1, max_length=120)
    department: str | None = Field(default=None, min_length=1, max_length=120)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{9,15}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(
            getattr(self, k) is None
            for k in self.model_fields_set - {"latitude", "longitude", "phone"}
        ):
            raise ValueError("Required branch fields cannot be null")
        return self


class AdministrativeBranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    address_line: str
    district: str
    city: str
    department: str
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    hours: list[HourInput] | None = None


class CandidateResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    account_status: str
    already_assigned: bool
