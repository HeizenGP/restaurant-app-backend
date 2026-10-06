from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.auth.application.exceptions import (
    TokenExpiredError,
    TokenInvalidError,
    TokenTypeMismatchError,
)
from app.modules.auth.domain.models import (
    OtpPurpose,
    Principal,
    PrincipalType,
    TokenType,
)
from app.modules.auth.infrastructure.security.tokens import (
    PyJwtTokenService,
    hash_refresh_token,
)

NOW = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
SECRET = "a-secure-test-secret-with-at-least-32-characters"


def build_service(
    *,
    secret: str = SECRET,
    issuer: str = "restaurant-app-backend",
    audience: str = "restaurant-app",
    access_ttl: timedelta = timedelta(minutes=15),
    clock_time: datetime = NOW,
) -> PyJwtTokenService:
    return PyJwtTokenService(
        secret=secret,
        algorithm="HS256",
        issuer=issuer,
        audience=audience,
        access_ttl=access_ttl,
        refresh_ttl=timedelta(days=30),
        phone_verification_ttl=timedelta(minutes=10),
        clock=lambda: clock_time,
    )


def registered_principal() -> Principal:
    return Principal(
        principal_type=PrincipalType.REGISTERED,
        user_id=uuid4(),
        customer_id=uuid4(),
    )


def test_access_token_round_trip_has_only_safe_identity_claims() -> None:
    service = build_service()
    principal = registered_principal()

    token = service.create_access_token(principal)
    claims = service.decode_access_token(token)

    assert claims.principal == principal
    assert claims.subject == str(principal.user_id)
    assert claims.token_type is TokenType.ACCESS
    assert claims.expires_at > claims.issued_at
    assert "correct horse" not in token
    assert "+519" not in token


def test_guest_access_token_round_trip() -> None:
    service = build_service()
    principal = Principal(
        principal_type=PrincipalType.GUEST,
        customer_id=uuid4(),
    )

    claims = service.decode_access_token(service.create_access_token(principal))

    assert claims.principal == principal
    assert claims.subject == str(principal.customer_id)


def test_refresh_token_is_only_for_registered_principal() -> None:
    service = build_service()
    principal = registered_principal()

    claims = service.decode_refresh_token(service.create_refresh_token(principal))

    assert claims.principal == principal
    assert claims.token_type is TokenType.REFRESH

    guest = Principal(
        principal_type=PrincipalType.GUEST,
        customer_id=uuid4(),
    )
    with pytest.raises(ValueError, match="registered"):
        service.create_refresh_token(guest)


def test_phone_verification_token_round_trip() -> None:
    service = build_service()

    token = service.create_phone_verification_token(
        "+51912345678", OtpPurpose.PHONE_VERIFY
    )
    claims = service.decode_phone_verification_token(token)

    assert claims.phone == "+51912345678"
    assert claims.subject == claims.phone
    assert claims.purpose is OtpPurpose.PHONE_VERIFY
    assert claims.token_type is TokenType.PHONE_VERIFICATION


def test_expired_token_is_rejected() -> None:
    service = build_service(
        access_ttl=timedelta(seconds=1),
        clock_time=datetime.now(UTC) - timedelta(minutes=1),
    )
    token = service.create_access_token(registered_principal())

    with pytest.raises(TokenExpiredError):
        service.decode_access_token(token)


@pytest.mark.parametrize(
    ("producer", "consumer"),
    [
        (
            {"secret": "another-secure-secret-with-32-characters"},
            {},
        ),
        (
            {"issuer": "unexpected-issuer"},
            {},
        ),
        (
            {"audience": "unexpected-audience"},
            {},
        ),
    ],
)
def test_signature_issuer_and_audience_are_strict(
    producer: dict[str, str],
    consumer: dict[str, str],
) -> None:
    token = build_service(**producer).create_access_token(registered_principal())

    with pytest.raises(TokenInvalidError):
        build_service(**consumer).decode_access_token(token)


def test_token_types_cannot_be_interchanged() -> None:
    service = build_service()
    refresh_token = service.create_refresh_token(registered_principal())

    with pytest.raises(TokenTypeMismatchError):
        service.decode_access_token(refresh_token)


def test_refresh_hash_is_sha256_and_rejects_empty_input() -> None:
    token = "high-entropy-refresh-token"

    assert hash_refresh_token(token) == (
        "b3c9f07f2e0f445724daff7466b4cf1e1dc6391e8e2905b8e62aca60568baab1"
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        hash_refresh_token("")
