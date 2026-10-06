from typing import Protocol

from app.modules.auth.application.types import (
    AccessTokenClaims,
    PasswordVerificationResult,
    PhoneVerificationTokenClaims,
    RefreshTokenClaims,
)
from app.modules.auth.domain.models import OtpPurpose, Principal


class PasswordHasher(Protocol):
    def hash_password(self, password: str) -> str:
        """Create a password hash suitable for persistent storage."""
        ...

    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password without exposing adapter-specific failures."""
        ...

    def verify_and_rehash(
        self, password: str, password_hash: str
    ) -> PasswordVerificationResult:
        """Verify and return a replacement hash when parameters are obsolete."""
        ...


class TokenService(Protocol):
    def create_access_token(self, principal: Principal) -> str:
        """Create a short-lived access token for a principal."""
        ...

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        """Validate and decode only an access token."""
        ...

    def create_refresh_token(self, principal: Principal) -> str:
        """Create a refresh token for a registered principal."""
        ...

    def decode_refresh_token(self, token: str) -> RefreshTokenClaims:
        """Validate and decode only a refresh token."""
        ...

    def create_phone_verification_token(self, phone: str, purpose: OtpPurpose) -> str:
        """Create a short-lived proof that an OTP challenge succeeded."""
        ...

    def decode_phone_verification_token(
        self, token: str
    ) -> PhoneVerificationTokenClaims:
        """Validate and decode only a phone-verification token."""
        ...


class OtpCodeService(Protocol):
    def generate_code(self) -> str:
        """Generate a cryptographically secure one-time code."""
        ...

    def hash_code(self, code: str) -> str:
        """Create a peppered digest for persistent storage."""
        ...

    def verify_code(self, code: str, code_hash: str) -> bool:
        """Compare an OTP with a stored digest in constant time."""
        ...


class OtpSender(Protocol):
    async def send_otp(self, *, phone: str, purpose: OtpPurpose, code: str) -> None:
        """Deliver an OTP without exposing it to normal application logs."""
        ...
