import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.modules.auth.application.errors import (
    AccountBlockedError,
    AccountDisabledError,
    CurrentPasswordInvalidError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    OtpAttemptsExceededError,
    OtpCooldownError,
    OtpDeliveryUnavailableError,
    OtpExpiredError,
    OtpInvalidError,
    PhoneAlreadyRegisteredError,
    RefreshTokenRevokedError,
    RegisteredCustomerLoginRequiredError,
    RegisteredUserRequiredError,
    TokenExpiredApplicationError,
    TokenInvalidApplicationError,
)
from app.modules.auth.application.services import AuthService, TokenPair
from app.modules.auth.domain.models import OtpPurpose, PrincipalType
from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)
from app.modules.auth.infrastructure.security.tokens import PyJwtTokenService
from app.shared.domain.time import utc_now
from tests.modules.auth.fakes import MemoryAuthRepository

PHONE = "+51987654321"
PASSWORD = "correct password without arbitrary complexity"


async def register(
    service: AuthService,
    tokens: PyJwtTokenService,
    *,
    phone: str = PHONE,
    email: str = "ana@example.com",
) -> TokenPair:
    return await service.register(
        verification_token=tokens.create_phone_verification_token(
            phone, OtpPurpose.REGISTER
        ),
        first_name="Ana",
        last_name="Ruiz",
        email=email,
        password=PASSWORD,
    )


def test_registration_creates_separate_verified_identity_and_customer_role(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
    password_hasher: PwdlibArgon2PasswordHasher,
) -> None:
    pair = asyncio.run(register(auth_service, token_service))
    user = next(iter(repository.users.values()))
    customer = next(iter(repository.customers.values()))
    assert customer.user_id == user.id
    assert customer.phone == user.phone == PHONE
    assert customer.full_name == "Ana Ruiz"
    assert user.phone_verified_at is not None
    assert user.password_hash.startswith("$argon2id$")
    assert password_hasher.verify_password(PASSWORD, user.password_hash)
    assert repository.user_roles == {(user.id, 1)}
    principal = token_service.decode_access_token(pair.access_token).principal
    assert principal.user_id == user.id and principal.customer_id == customer.id
    stored = next(iter(repository.refresh_tokens.values()))
    assert len(stored.token_hash) == 64 and stored.token_hash != pair.refresh_token
    assert repository.commits == 1


def test_guest_reuse_and_promotion_preserve_customer_identity(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        proof = token_service.create_phone_verification_token(
            PHONE, OtpPurpose.GUEST_ACCESS
        )
        guest = await auth_service.create_guest(
            verification_token=proof, full_name="Ana"
        )
        initial = token_service.decode_access_token(guest.access_token).principal
        assert len(repository.users) == len(repository.refresh_tokens) == 0
        reused = await auth_service.create_guest(
            verification_token=proof, full_name="Ana R."
        )
        assert (
            token_service.decode_access_token(reused.access_token).principal == initial
        )
        await register(auth_service, token_service)
        assert len(repository.customers) == 1
        assert next(iter(repository.customers)) == initial.customer_id
        with pytest.raises(TokenInvalidApplicationError):
            await auth_service.resolve_principal(guest.access_token)
        with pytest.raises(RegisteredCustomerLoginRequiredError):
            await auth_service.create_guest(
                verification_token=proof, full_name="Another"
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("duplicate", ["phone", "email"])
def test_registration_rejects_duplicates(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
    duplicate: str,
) -> None:
    async def scenario() -> None:
        await register(auth_service, token_service)
        expected = (
            PhoneAlreadyRegisteredError
            if duplicate == "phone"
            else EmailAlreadyRegisteredError
        )
        with pytest.raises(expected):
            await register(
                auth_service,
                token_service,
                phone=PHONE if duplicate == "phone" else "+51911111111",
                email="new@example.com" if duplicate == "phone" else "ANA@EXAMPLE.COM",
            )
        assert len(repository.users) == len(repository.customers) == 1

    asyncio.run(scenario())


def test_registration_rolls_back_all_identity_writes(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    repository.fail_commit = True
    with pytest.raises(RuntimeError):
        asyncio.run(register(auth_service, token_service))
    assert not repository.users and not repository.customers
    assert not repository.refresh_tokens and not repository.user_roles
    assert repository.rollbacks == 1


def test_phone_proof_purpose_cannot_be_swapped(
    auth_service: AuthService, token_service: PyJwtTokenService
) -> None:
    proof = token_service.create_phone_verification_token(
        PHONE, OtpPurpose.GUEST_ACCESS
    )
    with pytest.raises(TokenInvalidApplicationError):
        asyncio.run(
            auth_service.register(
                verification_token=proof,
                first_name="Ana",
                last_name=None,
                email=None,
                password=PASSWORD,
            )
        )


@pytest.mark.parametrize("identifier", [PHONE, "ANA@EXAMPLE.COM"])
def test_login_accepts_phone_or_email_and_updates_last_login(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
    identifier: str,
) -> None:
    async def scenario() -> None:
        await register(auth_service, token_service)
        pair = await auth_service.login(identifier, PASSWORD)
        principal = await auth_service.resolve_principal(pair.access_token)
        assert principal.user_id in repository.last_login
        assert repository.last_login[principal.user_id].tzinfo is not None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "identifier,password", [(PHONE, "wrong"), ("missing@example.com", PASSWORD)]
)
def test_login_has_same_error_for_bad_password_or_missing_account(
    auth_service: AuthService,
    token_service: PyJwtTokenService,
    identifier: str,
    password: str,
) -> None:
    async def scenario() -> None:
        await register(auth_service, token_service)
        with pytest.raises(InvalidCredentialsError, match="^Invalid credentials$"):
            await auth_service.login(identifier, password)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,error",
    [("BLOCKED", AccountBlockedError), ("DISABLED", AccountDisabledError)],
)
def test_state_changes_apply_to_login_refresh_and_existing_access(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
    status: str,
    error: type[Exception],
) -> None:
    async def scenario() -> None:
        pair = await register(auth_service, token_service)
        user = next(iter(repository.users.values()))
        repository.users[user.id] = replace(user, account_status=status)
        for operation in (
            auth_service.login(PHONE, PASSWORD),
            auth_service.refresh(pair.refresh_token),
            auth_service.resolve_principal(pair.access_token),
        ):
            with pytest.raises(error):
                await operation

    asyncio.run(scenario())


def test_deleted_accounts_cannot_login(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        await register(auth_service, token_service)
        user = next(iter(repository.users.values()))
        repository.users[user.id] = replace(user, deleted_at=utc_now())
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(PHONE, PASSWORD)

    asyncio.run(scenario())


def test_refresh_rotates_rejects_old_token_and_logout_persists(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        original = await register(auth_service, token_service)
        fresh = await auth_service.refresh(original.refresh_token)
        assert fresh.access_token != original.access_token
        assert fresh.refresh_token != original.refresh_token
        assert (
            sum(t.revoked_at is not None for t in repository.refresh_tokens.values())
            == 1
        )
        with pytest.raises(RefreshTokenRevokedError):
            await auth_service.refresh(original.refresh_token)
        await auth_service.logout(fresh.refresh_token)
        await auth_service.logout(fresh.refresh_token)
        with pytest.raises(RefreshTokenRevokedError):
            await auth_service.refresh(fresh.refresh_token)
        with pytest.raises(TokenInvalidApplicationError):
            await auth_service.refresh(fresh.access_token)

    asyncio.run(scenario())


def test_refresh_checks_database_expiry_and_missing_hash(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        pair = await register(auth_service, token_service)
        stored = next(iter(repository.refresh_tokens.values()))
        repository.refresh_tokens[stored.id] = replace(
            stored, expires_at=utc_now() - timedelta(seconds=1)
        )
        with pytest.raises(RefreshTokenRevokedError):
            await auth_service.refresh(pair.refresh_token)
        repository.refresh_tokens.clear()
        with pytest.raises(RefreshTokenRevokedError):
            await auth_service.refresh(pair.refresh_token)

    asyncio.run(scenario())


def test_password_change_revokes_all_refresh_tokens(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        pair = await register(auth_service, token_service)
        principal = await auth_service.resolve_principal(pair.access_token)
        with pytest.raises(CurrentPasswordInvalidError):
            await auth_service.change_password(principal, "wrong", "new valid password")
        await auth_service.change_password(principal, PASSWORD, "new valid password")
        assert all(t.revoked_at for t in repository.refresh_tokens.values())
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(PHONE, PASSWORD)
        await auth_service.login(PHONE, "new valid password")

    asyncio.run(scenario())


def test_phone_change_requires_proof_and_updates_both_identities(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        pair = await register(auth_service, token_service)
        principal = await auth_service.resolve_principal(pair.access_token)
        bad = token_service.create_phone_verification_token(
            "+51911111111", OtpPurpose.REGISTER
        )
        with pytest.raises(TokenInvalidApplicationError):
            await auth_service.change_phone(principal, bad)
        proof = token_service.create_phone_verification_token(
            "+51911111111", OtpPurpose.PHONE_VERIFY
        )
        await auth_service.change_phone(principal, proof)
        assert next(iter(repository.users.values())).phone == "+51911111111"
        assert next(iter(repository.customers.values())).phone == "+51911111111"

    asyncio.run(scenario())


def test_guest_cannot_change_account_credentials(
    auth_service: AuthService,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        proof = token_service.create_phone_verification_token(
            PHONE, OtpPurpose.GUEST_ACCESS
        )
        guest = await auth_service.create_guest(
            verification_token=proof, full_name="Ana"
        )
        principal = await auth_service.resolve_principal(guest.access_token)
        assert principal.principal_type is PrincipalType.GUEST
        with pytest.raises(RegisteredUserRequiredError):
            await auth_service.change_password(principal, PASSWORD, "a new password")
        with pytest.raises(RegisteredUserRequiredError):
            await auth_service.change_phone(principal, proof)

    asyncio.run(scenario())


def test_otp_cooldown_consumption_and_hashed_storage(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
) -> None:
    async def scenario() -> None:
        requested = await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)
        assert requested.debug_code is not None
        stored = next(iter(repository.challenges.values()))
        assert stored.code_hash != requested.debug_code
        with pytest.raises(OtpCooldownError):
            await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)
        await auth_service.verify_otp(PHONE, OtpPurpose.REGISTER, requested.debug_code)
        with pytest.raises(OtpInvalidError):
            await auth_service.verify_otp(
                PHONE, OtpPurpose.REGISTER, requested.debug_code
            )
        with pytest.raises(OtpCooldownError):
            await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)

    asyncio.run(scenario())


def test_wrong_otp_attempts_are_persisted_and_limited(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
) -> None:
    async def scenario() -> None:
        requested = await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)
        wrong = "000000" if requested.debug_code != "000000" else "999999"
        for expected in [
            OtpInvalidError,
            OtpInvalidError,
            OtpAttemptsExceededError,
            OtpAttemptsExceededError,
        ]:
            with pytest.raises(expected):
                await auth_service.verify_otp(PHONE, OtpPurpose.REGISTER, wrong)
        stored = next(iter(repository.challenges.values()))
        assert stored.attempts == stored.max_attempts == 3
        assert stored.consumed_at is not None

    asyncio.run(scenario())


def test_expired_otp_is_consumed(
    auth_service: AuthService, repository: MemoryAuthRepository
) -> None:
    async def scenario() -> None:
        requested = await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)
        stored = next(iter(repository.challenges.values()))
        repository.challenges[stored.id] = replace(
            stored, expires_at=utc_now() - timedelta(seconds=1)
        )
        with pytest.raises(OtpExpiredError):
            await auth_service.verify_otp(
                PHONE, OtpPurpose.REGISTER, requested.debug_code or ""
            )
        assert repository.challenges[stored.id].consumed_at is not None

    asyncio.run(scenario())


def test_resend_invalidates_previous_challenge(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
) -> None:
    async def scenario() -> None:
        await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)
        old = next(iter(repository.challenges.values()))
        repository.challenges[old.id] = replace(
            old, created_at=utc_now() - timedelta(seconds=61)
        )
        await auth_service.request_otp(PHONE, OtpPurpose.REGISTER)
        assert repository.challenges[old.id].consumed_at is not None
        assert len(repository.challenges) == 2

    asyncio.run(scenario())


def test_no_fake_sms_sender_is_used_outside_development(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
) -> None:
    auth_service._otp_sender = None
    with pytest.raises(OtpDeliveryUnavailableError):
        asyncio.run(auth_service.request_otp(PHONE, OtpPurpose.REGISTER))
    assert not repository.challenges


def test_expired_refresh_jwt_is_rejected(
    auth_service: AuthService,
    repository: MemoryAuthRepository,
    token_service: PyJwtTokenService,
) -> None:
    async def scenario() -> None:
        pair = await register(auth_service, token_service)
        principal = token_service.decode_access_token(pair.access_token).principal
        expired_service = PyJwtTokenService(
            secret="test-only-signing-key-with-at-least-32-characters",
            algorithm="HS256",
            issuer="tests",
            audience="tests",
            access_ttl=timedelta(minutes=1),
            refresh_ttl=timedelta(seconds=1),
            phone_verification_ttl=timedelta(minutes=1),
            clock=lambda: utc_now() - timedelta(minutes=5),
        )
        with pytest.raises(TokenExpiredApplicationError):
            await auth_service.refresh(expired_service.create_refresh_token(principal))

    asyncio.run(scenario())
