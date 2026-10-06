from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.auth.domain.models import OtpPurpose, Principal, TokenType


@dataclass(frozen=True, slots=True)
class PasswordVerificationResult:
    is_valid: bool
    updated_hash: str | None = None

    @property
    def needs_rehash(self) -> bool:
        return self.is_valid and self.updated_hash is not None


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject: str
    principal: Principal
    jti: UUID
    issued_at: datetime
    expires_at: datetime

    @property
    def token_type(self) -> TokenType:
        return TokenType.ACCESS


@dataclass(frozen=True, slots=True)
class RefreshTokenClaims:
    subject: str
    principal: Principal
    jti: UUID
    issued_at: datetime
    expires_at: datetime

    @property
    def token_type(self) -> TokenType:
        return TokenType.REFRESH


@dataclass(frozen=True, slots=True)
class PhoneVerificationTokenClaims:
    subject: str
    phone: str
    purpose: OtpPurpose
    jti: UUID
    issued_at: datetime
    expires_at: datetime

    @property
    def token_type(self) -> TokenType:
        return TokenType.PHONE_VERIFICATION
