import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.auth.application.errors import (
    AccountBlockedError,
    AccountDisabledError,
    AuthDataUnavailableError,
    CurrentPasswordInvalidError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidPasswordError,
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
from app.modules.auth.application.exceptions import (
    TokenExpiredError,
    TokenValidationError,
)
from app.modules.auth.application.ports import (
    OtpCodeService,
    OtpSender,
    PasswordHasher,
    TokenService,
)
from app.modules.auth.application.repository import (
    AuthRepository,
    CustomerIdentityData,
    UserData,
)
from app.modules.auth.application.security import RefreshTokenHasher
from app.modules.auth.application.types import (
    PhoneVerificationTokenClaims,
    RefreshTokenClaims,
)
from app.modules.auth.domain.models import (
    AccountStatus,
    OtpPurpose,
    Principal,
    PrincipalType,
)
from app.shared.application.exceptions import ApplicationError
from app.shared.domain.time import utc_now


@dataclass(frozen=True)
class OtpRequestResult:
    accepted: bool = True
    debug_code: str | None = None


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class GuestToken:
    access_token: str
    token_type: str
    expires_in: int


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        refresh_token_hasher: RefreshTokenHasher,
        otp_codes: OtpCodeService,
        otp_sender: OtpSender | None,
        dummy_password_hash: str,
        access_expires_seconds: int,
        otp_expires: timedelta,
        otp_max_attempts: int,
        otp_resend_cooldown: timedelta,
        expose_debug_otp: bool,
    ) -> None:
        self._repository = repository
        self._password_hasher = password_hasher
        self._token_service = token_service
        self._refresh_token_hasher = refresh_token_hasher
        self._otp_codes = otp_codes
        self._otp_sender = otp_sender
        self._dummy_password_hash = dummy_password_hash
        self._access_expires_seconds = access_expires_seconds
        self._otp_expires = otp_expires
        self._otp_max_attempts = otp_max_attempts
        self._otp_resend_cooldown = otp_resend_cooldown
        self._expose_debug_otp = expose_debug_otp

    async def request_otp(self, phone: str, purpose: OtpPurpose) -> OtpRequestResult:
        now = utc_now()
        latest = await self._repository.latest_otp(phone, purpose, lock=True)
        if latest is not None and latest.created_at + self._otp_resend_cooldown > now:
            raise OtpCooldownError()
        code = self._otp_codes.generate_code()
        try:
            await self._repository.invalidate_open_otps(phone, purpose, now)
            await self._repository.add_otp(
                phone=phone,
                purpose=purpose,
                code_hash=self._otp_codes.hash_code(code),
                expires_at=now + self._otp_expires,
                max_attempts=self._otp_max_attempts,
                created_at=now,
            )
            if self._otp_sender is None:
                raise OtpDeliveryUnavailableError()
            await self._otp_sender.send_otp(phone=phone, purpose=purpose, code=code)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return OtpRequestResult(debug_code=code if self._expose_debug_otp else None)

    async def verify_otp(self, phone: str, purpose: OtpPurpose, code: str) -> str:
        now = utc_now()
        challenge = await self._repository.latest_otp(phone, purpose, lock=True)
        if challenge is None:
            raise OtpInvalidError()
        if challenge.attempts >= challenge.max_attempts:
            raise OtpAttemptsExceededError()
        if challenge.consumed_at is not None:
            raise OtpInvalidError()
        if challenge.expires_at <= now:
            await self._repository.consume_otp(challenge.id, now)
            await self._repository.commit()
            raise OtpExpiredError()
        if not self._otp_codes.verify_code(code, challenge.code_hash):
            attempts = challenge.attempts + 1
            consumed_at = now if attempts >= challenge.max_attempts else None
            await self._repository.fail_otp_attempt(
                challenge.id, attempts=attempts, consumed_at=consumed_at
            )
            await self._repository.commit()
            if attempts >= challenge.max_attempts:
                raise OtpAttemptsExceededError()
            raise OtpInvalidError()
        await self._repository.consume_otp(challenge.id, now)
        await self._repository.commit()
        return self._token_service.create_phone_verification_token(phone, purpose)

    async def register(
        self,
        *,
        verification_token: str,
        first_name: str,
        last_name: str | None,
        email: str | None,
        password: str,
    ) -> TokenPair:
        claims = self._phone_claims(verification_token, OtpPurpose.REGISTER)
        self._validate_password(password)
        normalized_email = email.strip().lower() if email else None
        if await self._repository.get_user_by_phone(claims.phone) is not None:
            raise PhoneAlreadyRegisteredError()
        if (
            normalized_email is not None
            and await self._repository.get_user_by_email(normalized_email) is not None
        ):
            raise EmailAlreadyRegisteredError()
        role = await self._repository.get_role("CUSTOMER")
        if role is None or role.scope != "GLOBAL":
            raise AuthDataUnavailableError()
        now = utc_now()
        full_name = self._full_name(first_name, last_name)
        if not first_name.strip() or len(full_name) > 180:
            raise ApplicationError("Name is invalid")
        password_hash = await asyncio.to_thread(
            self._password_hasher.hash_password, password
        )
        try:
            guest = await self._repository.get_customer_by_phone(
                claims.phone, lock=True
            )
            if guest is not None and guest.user_id is not None:
                raise PhoneAlreadyRegisteredError()
            user = await self._repository.add_user(
                email=normalized_email,
                phone=claims.phone,
                password_hash=password_hash,
                first_name=first_name.strip(),
                last_name=last_name.strip() if last_name else None,
                verified_at=now,
            )
            await self._repository.add_user_role(user.id, role.id)
            customer = (
                await self._repository.promote_customer(
                    guest.id,
                    user_id=user.id,
                    full_name=full_name,
                    email=normalized_email,
                    verified_at=now,
                )
                if guest is not None
                else await self._repository.add_customer(
                    user_id=user.id,
                    full_name=full_name,
                    phone=claims.phone,
                    email=normalized_email,
                    verified_at=now,
                )
            )
            pair = await self._issue_pair(user, customer, now)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return pair

    async def create_guest(
        self, *, verification_token: str, full_name: str
    ) -> GuestToken:
        claims = self._phone_claims(verification_token, OtpPurpose.GUEST_ACCESS)
        if not full_name.strip() or len(full_name) > 180:
            raise ApplicationError("Name is invalid")
        now = utc_now()
        try:
            customer = await self._repository.get_customer_by_phone(
                claims.phone, lock=True
            )
            if customer is not None and customer.user_id is not None:
                raise RegisteredCustomerLoginRequiredError()
            if customer is None:
                customer = await self._repository.add_customer(
                    user_id=None,
                    full_name=full_name.strip(),
                    phone=claims.phone,
                    email=None,
                    verified_at=now,
                )
            else:
                customer = await self._repository.update_guest_name(
                    customer.id,
                    full_name=full_name.strip(),
                    verified_at=now,
                )
            principal = Principal(
                principal_type=PrincipalType.GUEST,
                customer_id=customer.id,
            )
            access_token = self._token_service.create_access_token(principal)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return GuestToken(
            access_token=access_token,
            token_type="bearer",
            expires_in=self._access_expires_seconds,
        )

    async def login(self, identifier: str, password: str) -> TokenPair:
        user = await self._repository.get_user_by_identifier(identifier.strip())
        password_hash = user.password_hash if user else self._dummy_password_hash
        verification = await asyncio.to_thread(
            self._password_hasher.verify_and_rehash, password, password_hash
        )
        if user is None or not verification.is_valid or user.deleted_at is not None:
            raise InvalidCredentialsError()
        self._ensure_active(user)
        customer = await self._repository.get_customer_by_user(user.id)
        now = utc_now()
        try:
            if verification.updated_hash is not None:
                await self._repository.update_password(
                    user.id, verification.updated_hash
                )
            await self._repository.update_last_login(user.id, logged_in_at=now)
            pair = await self._issue_pair(user, customer, now)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        claims = self._refresh_claims(refresh_token)
        now = utc_now()
        if claims.principal.user_id is None:
            raise TokenInvalidApplicationError()
        # Lock user before refresh rows, matching password-change lock order.
        user = await self._repository.get_user(claims.principal.user_id, lock=True)
        if user is None or user.deleted_at is not None:
            raise RefreshTokenRevokedError()
        self._ensure_active(user)
        stored = await self._repository.get_refresh_token_for_update(
            self._refresh_token_hasher.hash_token(refresh_token)
        )
        if (
            stored is None
            or stored.revoked_at is not None
            or stored.expires_at <= now
            or stored.user_id != claims.principal.user_id
        ):
            raise RefreshTokenRevokedError()
        customer = await self._repository.get_customer_by_user(user.id)
        try:
            await self._repository.revoke_refresh_token(stored.id, now)
            pair = await self._issue_pair(user, customer, now)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return pair

    async def logout(self, refresh_token: str) -> None:
        self._refresh_claims(refresh_token)
        stored = await self._repository.get_refresh_token_for_update(
            self._refresh_token_hasher.hash_token(refresh_token)
        )
        if stored is not None and stored.revoked_at is None:
            await self._repository.revoke_refresh_token(stored.id, utc_now())
            await self._repository.commit()

    async def change_password(
        self, principal: Principal, current_password: str, new_password: str
    ) -> None:
        user_id = self._registered_user_id(principal)
        self._validate_password(new_password)
        user = await self._repository.get_user(user_id, lock=True)
        if user is None:
            raise CurrentPasswordInvalidError()
        self._ensure_active(user)
        verified = await asyncio.to_thread(
            self._password_hasher.verify_password, current_password, user.password_hash
        )
        if not verified:
            raise CurrentPasswordInvalidError()
        password_hash = await asyncio.to_thread(
            self._password_hasher.hash_password, new_password
        )
        now = utc_now()
        try:
            await self._repository.update_password(user_id, password_hash)
            await self._repository.revoke_all_refresh_tokens(user_id, now)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise

    async def change_phone(self, principal: Principal, verification_token: str) -> None:
        user_id = self._registered_user_id(principal)
        if principal.customer_id is None:
            raise AuthDataUnavailableError()
        claims = self._phone_claims(verification_token, OtpPurpose.PHONE_VERIFY)
        user_with_phone = await self._repository.get_user_by_phone(claims.phone)
        if user_with_phone is not None and user_with_phone.id != user_id:
            raise PhoneAlreadyRegisteredError()
        customer_with_phone = await self._repository.get_customer_by_phone(
            claims.phone, lock=True
        )
        if (
            customer_with_phone is not None
            and customer_with_phone.id != principal.customer_id
        ):
            raise PhoneAlreadyRegisteredError()
        try:
            await self._repository.update_phone(
                user_id,
                principal.customer_id,
                phone=claims.phone,
                verified_at=utc_now(),
            )
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise

    async def resolve_principal(self, access_token: str) -> Principal:
        try:
            principal = self._token_service.decode_access_token(access_token).principal
        except TokenExpiredError:
            raise TokenExpiredApplicationError() from None
        except TokenValidationError:
            raise TokenInvalidApplicationError() from None
        if principal.principal_type is PrincipalType.REGISTERED:
            if principal.user_id is None:
                raise TokenInvalidApplicationError()
            user = await self._repository.get_user(principal.user_id)
            if user is None or user.deleted_at is not None:
                raise TokenInvalidApplicationError()
            self._ensure_active(user)
            customer = await self._repository.get_customer_by_user(user.id)
            if (customer.id if customer is not None else None) != principal.customer_id:
                raise TokenInvalidApplicationError()
            return principal
        if principal.customer_id is None:
            raise TokenInvalidApplicationError()
        customer = await self._repository.get_customer(principal.customer_id)
        if customer is None or customer.user_id is not None:
            raise TokenInvalidApplicationError()
        return principal

    async def _issue_pair(
        self,
        user: UserData,
        customer: CustomerIdentityData | None,
        issued_at: datetime,
    ) -> TokenPair:
        principal = Principal(
            principal_type=PrincipalType.REGISTERED,
            user_id=user.id,
            customer_id=customer.id if customer is not None else None,
        )
        access_token = self._token_service.create_access_token(principal)
        refresh_token = self._token_service.create_refresh_token(principal)
        refresh_claims = self._token_service.decode_refresh_token(refresh_token)
        await self._repository.add_refresh_token(
            token_id=refresh_claims.jti,
            user_id=user.id,
            token_hash=self._refresh_token_hasher.hash_token(refresh_token),
            expires_at=refresh_claims.expires_at,
            created_at=issued_at,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=self._access_expires_seconds,
        )

    def _phone_claims(
        self, token: str, purpose: OtpPurpose
    ) -> PhoneVerificationTokenClaims:
        try:
            claims = self._token_service.decode_phone_verification_token(token)
        except TokenExpiredError:
            raise TokenExpiredApplicationError() from None
        except TokenValidationError:
            raise TokenInvalidApplicationError() from None
        if claims.purpose is not purpose:
            raise TokenInvalidApplicationError()
        return claims

    def _refresh_claims(self, token: str) -> RefreshTokenClaims:
        try:
            return self._token_service.decode_refresh_token(token)
        except TokenExpiredError:
            raise TokenExpiredApplicationError() from None
        except TokenValidationError:
            raise TokenInvalidApplicationError() from None

    @staticmethod
    def _ensure_active(user: UserData) -> None:
        if user.deleted_at is not None:
            raise InvalidCredentialsError()
        if user.account_status == AccountStatus.BLOCKED:
            raise AccountBlockedError()
        if user.account_status == AccountStatus.DISABLED:
            raise AccountDisabledError()
        if user.account_status != AccountStatus.ACTIVE:
            raise InvalidCredentialsError()

    @staticmethod
    def _registered_user_id(principal: Principal) -> UUID:
        if (
            principal.principal_type is not PrincipalType.REGISTERED
            or principal.user_id is None
        ):
            raise RegisteredUserRequiredError()
        return principal.user_id

    @staticmethod
    def _validate_password(password: str) -> None:
        if not 8 <= len(password) <= 128 or not password.strip():
            raise InvalidPasswordError()

    @staticmethod
    def _full_name(first_name: str, last_name: str | None) -> str:
        return " ".join(part for part in (first_name.strip(), last_name or "") if part)
