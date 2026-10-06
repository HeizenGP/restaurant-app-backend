from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from uuid import UUID, uuid4

from app.modules.auth.application.repository import (
    CustomerIdentityData,
    OtpChallengeData,
    RefreshTokenData,
    RoleData,
    UserData,
)
from app.modules.auth.domain.models import OtpPurpose


class MemoryAuthRepository:
    """Transactional test double; never connects to the development database."""

    def __init__(self) -> None:
        self.users: dict[UUID, UserData] = {}
        self.customers: dict[UUID, CustomerIdentityData] = {}
        self.challenges: dict[UUID, OtpChallengeData] = {}
        self.refresh_tokens: dict[UUID, RefreshTokenData] = {}
        self.roles = {"CUSTOMER": RoleData(id=1, code="CUSTOMER", scope="GLOBAL")}
        self.user_roles: set[tuple[UUID, int]] = set()
        self.last_login: dict[UUID, datetime] = {}
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False
        self._snapshot = self._state()

    def _state(self) -> tuple:
        return deepcopy(
            (
                self.users,
                self.customers,
                self.challenges,
                self.refresh_tokens,
                self.user_roles,
                self.last_login,
            )
        )

    async def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("simulated persistence failure")
        self.commits += 1
        self._snapshot = self._state()

    async def rollback(self) -> None:
        self.rollbacks += 1
        (
            self.users,
            self.customers,
            self.challenges,
            self.refresh_tokens,
            self.user_roles,
            self.last_login,
        ) = deepcopy(self._snapshot)

    async def latest_otp(
        self, phone: str, purpose: OtpPurpose, *, lock: bool = False
    ) -> OtpChallengeData | None:
        matches = [
            row
            for row in self.challenges.values()
            if row.phone == phone and row.purpose == purpose
        ]
        return max(matches, key=lambda row: row.created_at, default=None)

    async def invalidate_open_otps(
        self, phone: str, purpose: OtpPurpose, consumed_at: datetime
    ) -> None:
        for key, row in list(self.challenges.items()):
            if (
                row.phone == phone
                and row.purpose == purpose
                and row.consumed_at is None
            ):
                self.challenges[key] = replace(row, consumed_at=consumed_at)

    async def add_otp(
        self,
        *,
        phone: str,
        purpose: OtpPurpose,
        code_hash: str,
        expires_at: datetime,
        max_attempts: int,
        created_at: datetime,
    ) -> OtpChallengeData:
        row = OtpChallengeData(
            id=uuid4(),
            phone=phone,
            purpose=purpose,
            code_hash=code_hash,
            expires_at=expires_at,
            consumed_at=None,
            attempts=0,
            max_attempts=max_attempts,
            created_at=created_at,
        )
        self.challenges[row.id] = row
        return row

    async def consume_otp(self, challenge_id: UUID, consumed_at: datetime) -> None:
        self.challenges[challenge_id] = replace(
            self.challenges[challenge_id], consumed_at=consumed_at
        )

    async def fail_otp_attempt(
        self, challenge_id: UUID, *, attempts: int, consumed_at: datetime | None
    ) -> None:
        self.challenges[challenge_id] = replace(
            self.challenges[challenge_id], attempts=attempts, consumed_at=consumed_at
        )

    async def get_user_by_phone(self, phone: str) -> UserData | None:
        return next((u for u in self.users.values() if u.phone == phone), None)

    async def get_user_by_email(self, email: str) -> UserData | None:
        return next(
            (
                u
                for u in self.users.values()
                if u.email and u.email.lower() == email.lower()
            ),
            None,
        )

    async def get_user_by_identifier(self, identifier: str) -> UserData | None:
        return await self.get_user_by_email(identifier) or await self.get_user_by_phone(
            identifier
        )

    async def get_user(self, user_id: UUID, *, lock: bool = False) -> UserData | None:
        return self.users.get(user_id)

    async def get_customer_by_phone(
        self, phone: str, *, lock: bool = False
    ) -> CustomerIdentityData | None:
        return next((c for c in self.customers.values() if c.phone == phone), None)

    async def get_customer_by_user(self, user_id: UUID) -> CustomerIdentityData | None:
        return next((c for c in self.customers.values() if c.user_id == user_id), None)

    async def get_customer(self, customer_id: UUID) -> CustomerIdentityData | None:
        return self.customers.get(customer_id)

    async def get_role(self, code: str) -> RoleData | None:
        return self.roles.get(code)

    async def add_user(
        self,
        *,
        email: str | None,
        phone: str,
        password_hash: str,
        first_name: str,
        last_name: str | None,
        verified_at: datetime,
    ) -> UserData:
        row = UserData(
            id=uuid4(),
            email=email,
            phone=phone,
            password_hash=password_hash,
            first_name=first_name,
            last_name=last_name,
            account_status="ACTIVE",
            phone_verified_at=verified_at,
            deleted_at=None,
        )
        self.users[row.id] = row
        return row

    async def add_user_role(self, user_id: UUID, role_id: int) -> None:
        self.user_roles.add((user_id, role_id))

    async def add_customer(
        self,
        *,
        user_id: UUID | None,
        full_name: str,
        phone: str,
        email: str | None,
        verified_at: datetime,
    ) -> CustomerIdentityData:
        row = CustomerIdentityData(
            id=uuid4(),
            user_id=user_id,
            full_name=full_name,
            phone=phone,
            email=email,
            phone_verified_at=verified_at,
        )
        self.customers[row.id] = row
        return row

    async def promote_customer(
        self,
        customer_id: UUID,
        *,
        user_id: UUID,
        full_name: str,
        email: str | None,
        verified_at: datetime,
    ) -> CustomerIdentityData:
        row = replace(
            self.customers[customer_id],
            user_id=user_id,
            full_name=full_name,
            email=email,
            phone_verified_at=verified_at,
        )
        self.customers[customer_id] = row
        return row

    async def update_guest_name(
        self, customer_id: UUID, *, full_name: str, verified_at: datetime
    ) -> CustomerIdentityData:
        row = replace(
            self.customers[customer_id],
            full_name=full_name,
            phone_verified_at=verified_at,
        )
        self.customers[customer_id] = row
        return row

    async def update_last_login(self, user_id: UUID, *, logged_in_at: datetime) -> None:
        self.last_login[user_id] = logged_in_at

    async def update_password(self, user_id: UUID, password_hash: str) -> None:
        self.users[user_id] = replace(self.users[user_id], password_hash=password_hash)

    async def update_phone(
        self, user_id: UUID, customer_id: UUID, *, phone: str, verified_at: datetime
    ) -> None:
        self.users[user_id] = replace(
            self.users[user_id], phone=phone, phone_verified_at=verified_at
        )
        self.customers[customer_id] = replace(
            self.customers[customer_id], phone=phone, phone_verified_at=verified_at
        )

    async def add_refresh_token(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> None:
        self.refresh_tokens[token_id] = RefreshTokenData(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked_at=None,
            created_at=created_at,
        )

    async def get_refresh_token_for_update(
        self, token_hash: str
    ) -> RefreshTokenData | None:
        return next(
            (t for t in self.refresh_tokens.values() if t.token_hash == token_hash),
            None,
        )

    async def revoke_refresh_token(self, token_id: UUID, revoked_at: datetime) -> None:
        self.refresh_tokens[token_id] = replace(
            self.refresh_tokens[token_id], revoked_at=revoked_at
        )

    async def revoke_all_refresh_tokens(
        self, user_id: UUID, revoked_at: datetime
    ) -> None:
        for key, row in list(self.refresh_tokens.items()):
            if row.user_id == user_id and row.revoked_at is None:
                self.refresh_tokens[key] = replace(row, revoked_at=revoked_at)
