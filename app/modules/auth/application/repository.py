from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.auth.domain.models import OtpPurpose


@dataclass(frozen=True)
class UserData:
    id: UUID
    email: str | None
    phone: str | None
    password_hash: str
    first_name: str
    last_name: str | None
    account_status: str
    phone_verified_at: datetime | None
    deleted_at: datetime | None


@dataclass(frozen=True)
class CustomerIdentityData:
    id: UUID
    user_id: UUID | None
    full_name: str
    phone: str
    email: str | None
    phone_verified_at: datetime | None


@dataclass(frozen=True)
class RoleData:
    id: int
    code: str
    scope: str


@dataclass(frozen=True)
class OtpChallengeData:
    id: UUID
    phone: str
    purpose: OtpPurpose
    code_hash: str
    expires_at: datetime
    consumed_at: datetime | None
    attempts: int
    max_attempts: int
    created_at: datetime


@dataclass(frozen=True)
class RefreshTokenData:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class AuthRepository(Protocol):
    async def latest_otp(
        self, phone: str, purpose: OtpPurpose, *, lock: bool = False
    ) -> OtpChallengeData | None: ...

    async def invalidate_open_otps(
        self, phone: str, purpose: OtpPurpose, consumed_at: datetime
    ) -> None: ...

    async def add_otp(
        self,
        *,
        phone: str,
        purpose: OtpPurpose,
        code_hash: str,
        expires_at: datetime,
        max_attempts: int,
        created_at: datetime,
    ) -> OtpChallengeData: ...

    async def consume_otp(self, challenge_id: UUID, consumed_at: datetime) -> None: ...

    async def fail_otp_attempt(
        self, challenge_id: UUID, *, attempts: int, consumed_at: datetime | None
    ) -> None: ...

    async def get_user_by_phone(self, phone: str) -> UserData | None: ...

    async def get_user_by_email(self, email: str) -> UserData | None: ...

    async def get_user_by_identifier(self, identifier: str) -> UserData | None: ...

    async def get_user(
        self, user_id: UUID, *, lock: bool = False
    ) -> UserData | None: ...

    async def get_customer_by_phone(
        self, phone: str, *, lock: bool = False
    ) -> CustomerIdentityData | None: ...

    async def get_customer_by_user(
        self, user_id: UUID
    ) -> CustomerIdentityData | None: ...

    async def get_customer(self, customer_id: UUID) -> CustomerIdentityData | None: ...

    async def get_role(self, code: str) -> RoleData | None: ...

    async def add_user(
        self,
        *,
        email: str | None,
        phone: str,
        password_hash: str,
        first_name: str,
        last_name: str | None,
        verified_at: datetime,
    ) -> UserData: ...

    async def add_user_role(self, user_id: UUID, role_id: int) -> None: ...

    async def add_customer(
        self,
        *,
        user_id: UUID | None,
        full_name: str,
        phone: str,
        email: str | None,
        verified_at: datetime,
    ) -> CustomerIdentityData: ...

    async def promote_customer(
        self,
        customer_id: UUID,
        *,
        user_id: UUID,
        full_name: str,
        email: str | None,
        verified_at: datetime,
    ) -> CustomerIdentityData: ...

    async def update_guest_name(
        self, customer_id: UUID, *, full_name: str, verified_at: datetime
    ) -> CustomerIdentityData: ...

    async def update_last_login(
        self, user_id: UUID, *, logged_in_at: datetime
    ) -> None: ...

    async def update_password(self, user_id: UUID, password_hash: str) -> None: ...

    async def update_phone(
        self,
        user_id: UUID,
        customer_id: UUID,
        *,
        phone: str,
        verified_at: datetime,
    ) -> None: ...

    async def add_refresh_token(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> None: ...

    async def get_refresh_token_for_update(
        self, token_hash: str
    ) -> RefreshTokenData | None: ...

    async def revoke_refresh_token(
        self, token_id: UUID, revoked_at: datetime
    ) -> None: ...

    async def revoke_all_refresh_tokens(
        self, user_id: UUID, revoked_at: datetime
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
