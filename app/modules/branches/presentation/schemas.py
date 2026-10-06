from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BranchHourResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    day_of_week: int
    open_time: time | None
    close_time: time | None
    is_closed: bool


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    address_line: str
    district: str | None
    city: str
    department: str
    latitude: Decimal | None
    longitude: Decimal | None
    phone: str | None
    timezone: str
    hours: tuple[BranchHourResponse, ...]


class CreateStaffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    user_id: UUID
    role_code: str = Field(min_length=1, max_length=40)
    employee_code: str = Field(min_length=1, max_length=40)


class UpdateStaffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role_code: str | None = Field(default=None, min_length=1, max_length=40)
    employee_code: str | None = Field(default=None, min_length=1, max_length=40)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UpdateStaffRequest":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Fields cannot be null")
        return self


class StaffAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    branch_id: UUID
    role_code: str
    employee_code: str
    is_active: bool
    assigned_at: datetime
    ended_at: datetime | None
