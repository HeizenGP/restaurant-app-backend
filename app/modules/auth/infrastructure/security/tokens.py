import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import jwt
from jwt import ExpiredSignatureError
from jwt import InvalidTokenError as PyJwtInvalidTokenError

from app.modules.auth.application.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    TokenTypeMismatchError,
)
from app.modules.auth.application.types import (
    AccessTokenClaims,
    PhoneVerificationTokenClaims,
    RefreshTokenClaims,
)
from app.modules.auth.domain.models import (
    OtpPurpose,
    Principal,
    PrincipalType,
    TokenType,
)

Clock = Callable[[], datetime]
_ALLOWED_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
_PHONE_PATTERN = re.compile(r"^\+?[0-9]{9,15}$")


def hash_refresh_token(token: str) -> str:
    """Hash a high-entropy refresh token for equality lookup in storage."""

    if not token:
        raise ValueError("Refresh token cannot be empty")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PyJwtTokenService:
    """PyJWT adapter with purpose-specific creation and strict decoding."""

    __slots__ = (
        "_access_ttl",
        "_algorithm",
        "_audience",
        "_clock",
        "_issuer",
        "_phone_verification_ttl",
        "_refresh_ttl",
        "_secret",
    )

    def __init__(
        self,
        *,
        secret: str,
        algorithm: str,
        issuer: str,
        audience: str,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
        phone_verification_ttl: timedelta,
        clock: Clock | None = None,
    ) -> None:
        if not secret:
            raise ValueError("JWT secret cannot be empty")
        if algorithm not in _ALLOWED_ALGORITHMS:
            raise ValueError("JWT algorithm must be an HMAC SHA-2 algorithm")
        if not issuer:
            raise ValueError("JWT issuer cannot be empty")
        if not audience:
            raise ValueError("JWT audience cannot be empty")

        lifetimes = {
            "access_ttl": access_ttl,
            "refresh_ttl": refresh_ttl,
            "phone_verification_ttl": phone_verification_ttl,
        }
        for name, lifetime in lifetimes.items():
            if lifetime <= timedelta(0):
                raise ValueError(f"{name} must be positive")

        self._secret = secret
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._phone_verification_ttl = phone_verification_ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_access_token(self, principal: Principal) -> str:
        payload = self._base_payload(
            subject=self._principal_subject(principal),
            token_type=TokenType.ACCESS,
            lifetime=self._access_ttl,
        )
        payload["principal_type"] = principal.principal_type.value
        if principal.user_id is not None:
            payload["user_id"] = str(principal.user_id)
        if principal.customer_id is not None:
            payload["customer_id"] = str(principal.customer_id)
        return self._encode(payload)

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        payload = self._decode(token, expected_type=TokenType.ACCESS)
        subject, jti, issued_at, expires_at = self._metadata(payload)
        principal = self._principal_from_payload(payload)

        if subject != self._principal_subject(principal):
            raise TokenInvalidError("Token subject does not match its principal")

        return AccessTokenClaims(
            subject=subject,
            principal=principal,
            jti=jti,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def create_refresh_token(self, principal: Principal) -> str:
        if principal.principal_type is not PrincipalType.REGISTERED:
            raise ValueError("Refresh tokens require a registered principal")

        payload = self._base_payload(
            subject=self._principal_subject(principal),
            token_type=TokenType.REFRESH,
            lifetime=self._refresh_ttl,
        )
        payload["principal_type"] = PrincipalType.REGISTERED.value
        payload["user_id"] = str(principal.user_id)
        if principal.customer_id is not None:
            payload["customer_id"] = str(principal.customer_id)
        return self._encode(payload)

    def decode_refresh_token(self, token: str) -> RefreshTokenClaims:
        payload = self._decode(token, expected_type=TokenType.REFRESH)
        subject, jti, issued_at, expires_at = self._metadata(payload)
        principal = self._principal_from_payload(payload)

        if principal.principal_type is not PrincipalType.REGISTERED:
            raise TokenInvalidError("Refresh token principal must be registered")
        if subject != str(principal.user_id):
            raise TokenInvalidError("Token subject does not match its principal")

        return RefreshTokenClaims(
            subject=subject,
            principal=principal,
            jti=jti,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def create_phone_verification_token(self, phone: str, purpose: OtpPurpose) -> str:
        if _PHONE_PATTERN.fullmatch(phone) is None:
            raise ValueError("Phone has an invalid format")

        payload = self._base_payload(
            subject=phone,
            token_type=TokenType.PHONE_VERIFICATION,
            lifetime=self._phone_verification_ttl,
        )
        payload["phone"] = phone
        payload["purpose"] = purpose.value
        return self._encode(payload)

    def decode_phone_verification_token(
        self, token: str
    ) -> PhoneVerificationTokenClaims:
        payload = self._decode(
            token,
            expected_type=TokenType.PHONE_VERIFICATION,
        )
        subject, jti, issued_at, expires_at = self._metadata(payload)
        phone = self._required_text(payload, "phone")
        if _PHONE_PATTERN.fullmatch(phone) is None or subject != phone:
            raise TokenInvalidError("Phone verification token is invalid")

        try:
            purpose = OtpPurpose(self._required_text(payload, "purpose"))
        except ValueError:
            raise TokenInvalidError("Phone verification purpose is invalid") from None

        return PhoneVerificationTokenClaims(
            subject=subject,
            phone=phone,
            purpose=purpose,
            jti=jti,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def _base_payload(
        self,
        *,
        subject: str,
        token_type: TokenType,
        lifetime: timedelta,
    ) -> dict[str, object]:
        issued_at = self._now()
        return {
            "sub": subject,
            "iat": issued_at,
            "exp": issued_at + lifetime,
            "jti": str(uuid4()),
            "iss": self._issuer,
            "aud": self._audience,
            "token_type": token_type.value,
        }

    def _encode(self, payload: dict[str, object]) -> str:
        return jwt.encode(
            payload,
            self._secret,
            algorithm=self._algorithm,
        )

    def _decode(self, token: str, *, expected_type: TokenType) -> dict[str, object]:
        try:
            decoded = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": [
                        "sub",
                        "iat",
                        "exp",
                        "jti",
                        "iss",
                        "aud",
                        "token_type",
                    ],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except ExpiredSignatureError:
            raise TokenExpiredError("Token has expired") from None
        except PyJwtInvalidTokenError:
            raise TokenInvalidError("Token is invalid") from None

        payload = cast(dict[str, object], decoded)
        if payload.get("token_type") != expected_type.value:
            raise TokenTypeMismatchError(f"Expected a {expected_type.value} token")
        return payload

    def _metadata(
        self, payload: dict[str, object]
    ) -> tuple[str, UUID, datetime, datetime]:
        subject = self._required_text(payload, "sub")
        try:
            jti = UUID(self._required_text(payload, "jti"))
            issued_at = self._numeric_date(payload, "iat")
            expires_at = self._numeric_date(payload, "exp")
        except (TypeError, ValueError):
            raise TokenInvalidError("Token metadata is invalid") from None

        if expires_at <= issued_at:
            raise TokenInvalidError("Token expiry is invalid")
        return subject, jti, issued_at, expires_at

    def _principal_from_payload(self, payload: dict[str, object]) -> Principal:
        try:
            principal_type = PrincipalType(
                self._required_text(payload, "principal_type")
            )
            user_id = self._optional_uuid(payload, "user_id")
            customer_id = self._optional_uuid(payload, "customer_id")
            return Principal(
                principal_type=principal_type,
                user_id=user_id,
                customer_id=customer_id,
            )
        except (TypeError, ValueError):
            raise TokenInvalidError("Token principal is invalid") from None

    @staticmethod
    def _principal_subject(principal: Principal) -> str:
        if principal.principal_type is PrincipalType.REGISTERED:
            return str(principal.user_id)
        return str(principal.customer_id)

    @staticmethod
    def _required_text(payload: dict[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise TokenInvalidError(f"Token claim {name} is invalid")
        return value

    @staticmethod
    def _optional_uuid(payload: dict[str, object], name: str) -> UUID | None:
        value = payload.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise TokenInvalidError(f"Token claim {name} is invalid")
        return UUID(value)

    @staticmethod
    def _numeric_date(payload: dict[str, object], name: str) -> datetime:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TokenInvalidError(f"Token claim {name} is invalid")
        return datetime.fromtimestamp(value, tz=UTC)

    def _now(self) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("JWT clock must return a timezone-aware datetime")
        return current.astimezone(UTC)
