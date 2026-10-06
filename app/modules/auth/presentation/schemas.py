import unicodedata
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)

from app.modules.auth.domain.models import OtpPurpose

Phone = Annotated[str, StringConstraints(pattern=r"^\+?[0-9]{9,15}$")]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def validate_text(cls, value: object) -> object:
        if isinstance(value, str) and (
            not value.strip()
            or any(unicodedata.category(c).startswith("C") for c in value)
        ):
            raise ValueError("Text must not be blank or contain control characters")
        return value


class OtpRequest(RequestModel):
    phone: Phone
    purpose: OtpPurpose


class OtpRequestResponse(BaseModel):
    accepted: Literal[True]
    debug_code: str | None = None


class OtpVerifyRequest(RequestModel):
    phone: Phone
    purpose: OtpPurpose
    code: str = Field(pattern=r"^[0-9]{6}$")


class OtpVerifyResponse(BaseModel):
    verification_token: str
    token_type: Literal["phone_verification"] = "phone_verification"


class RegisterRequest(RequestModel):
    verification_token: str = Field(min_length=1, max_length=4096)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    password: SecretStr = Field(min_length=8, max_length=128)


class GuestRequest(RequestModel):
    verification_token: str = Field(min_length=1, max_length=4096)
    full_name: str = Field(min_length=1, max_length=180)


class LoginRequest(RequestModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)


class RefreshRequest(RequestModel):
    refresh_token: SecretStr = Field(min_length=1, max_length=4096)


class LogoutRequest(RequestModel):
    refresh_token: SecretStr = Field(min_length=1, max_length=4096)


class PasswordChangeRequest(RequestModel):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=8, max_length=128)


class PhoneChangeRequest(RequestModel):
    verification_token: str = Field(min_length=1, max_length=4096)


class TokenPairResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"]
    expires_in: int


class GuestTokenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
