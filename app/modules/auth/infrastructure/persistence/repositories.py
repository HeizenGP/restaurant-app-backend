from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.application.errors import (
    AuthDataUnavailableError,
    EmailAlreadyRegisteredError,
    IdentityConflictError,
    PhoneAlreadyRegisteredError,
)
from app.modules.auth.application.repository import (
    CustomerIdentityData,
    OtpChallengeData,
    RefreshTokenData,
    RoleData,
    UserData,
)
from app.modules.auth.domain.models import OtpPurpose
from app.modules.auth.infrastructure.persistence.models import (
    RefreshTokenModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from app.modules.customers.infrastructure.persistence.models import (
    CustomerModel,
    OtpChallengeModel,
)
from app.shared.domain.time import utc_now


class SQLAlchemyAuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _user(model: UserModel) -> UserData:
        return UserData(
            id=model.id,
            email=model.email,
            phone=model.phone,
            password_hash=model.password_hash,
            first_name=model.first_name,
            last_name=model.last_name,
            account_status=model.account_status,
            phone_verified_at=model.phone_verified_at,
            deleted_at=model.deleted_at,
        )

    @staticmethod
    def _customer(model: CustomerModel) -> CustomerIdentityData:
        return CustomerIdentityData(
            id=model.id,
            user_id=model.user_id,
            full_name=model.full_name,
            phone=model.phone,
            email=model.email,
            phone_verified_at=model.phone_verified_at,
        )

    @staticmethod
    def _otp(model: OtpChallengeModel) -> OtpChallengeData:
        return OtpChallengeData(
            id=model.id,
            phone=model.phone,
            purpose=OtpPurpose(model.purpose),
            code_hash=model.code_hash,
            expires_at=model.expires_at,
            consumed_at=model.consumed_at,
            attempts=model.attempts,
            max_attempts=model.max_attempts,
            created_at=model.created_at,
        )

    @staticmethod
    def _refresh(model: RefreshTokenModel) -> RefreshTokenData:
        return RefreshTokenData(
            id=model.id,
            user_id=model.user_id,
            token_hash=model.token_hash,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
            created_at=model.created_at,
        )

    async def latest_otp(
        self, phone: str, purpose: OtpPurpose, *, lock: bool = False
    ) -> OtpChallengeData | None:
        if lock:
            # Serializes first requests too, when no row exists to lock yet.
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"otp:{phone}:{purpose.value}"},
            )
        query = (
            select(OtpChallengeModel)
            .where(
                OtpChallengeModel.phone == phone,
                OtpChallengeModel.purpose == purpose.value,
            )
            .order_by(OtpChallengeModel.created_at.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update()
        model = (await self._session.execute(query)).scalar_one_or_none()
        return None if model is None else self._otp(model)

    async def invalidate_open_otps(
        self, phone: str, purpose: OtpPurpose, consumed_at: datetime
    ) -> None:
        await self._session.execute(
            update(OtpChallengeModel)
            .where(
                OtpChallengeModel.phone == phone,
                OtpChallengeModel.purpose == purpose.value,
                OtpChallengeModel.consumed_at.is_(None),
            )
            .values(consumed_at=consumed_at)
        )

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
        model = OtpChallengeModel(
            id=uuid4(),
            phone=phone,
            purpose=purpose.value,
            code_hash=code_hash,
            expires_at=expires_at,
            attempts=0,
            max_attempts=max_attempts,
            created_at=created_at,
        )
        self._session.add(model)
        return self._otp(model)

    async def consume_otp(self, challenge_id: UUID, consumed_at: datetime) -> None:
        await self._session.execute(
            update(OtpChallengeModel)
            .where(OtpChallengeModel.id == challenge_id)
            .values(consumed_at=consumed_at)
        )

    async def fail_otp_attempt(
        self, challenge_id: UUID, *, attempts: int, consumed_at: datetime | None
    ) -> None:
        await self._session.execute(
            update(OtpChallengeModel)
            .where(OtpChallengeModel.id == challenge_id)
            .values(attempts=attempts, consumed_at=consumed_at)
        )

    async def get_user_by_phone(self, phone: str) -> UserData | None:
        return await self._one_user(select(UserModel).where(UserModel.phone == phone))

    async def get_user_by_email(self, email: str) -> UserData | None:
        return await self._one_user(select(UserModel).where(UserModel.email == email))

    async def get_user_by_identifier(self, identifier: str) -> UserData | None:
        return await self._one_user(
            select(UserModel)
            .where(or_(UserModel.email == identifier, UserModel.phone == identifier))
            .with_for_update()
        )

    async def _one_user(self, query: Select[tuple[UserModel]]) -> UserData | None:
        model = (await self._session.execute(query)).scalar_one_or_none()
        return None if model is None else self._user(model)

    async def get_user(self, user_id: UUID, *, lock: bool = False) -> UserData | None:
        query = select(UserModel).where(UserModel.id == user_id)
        if lock:
            query = query.with_for_update()
        return await self._one_user(query)

    async def get_customer_by_phone(
        self, phone: str, *, lock: bool = False
    ) -> CustomerIdentityData | None:
        query = select(CustomerModel).where(CustomerModel.phone == phone)
        if lock:
            query = query.with_for_update()
        model = (await self._session.execute(query)).scalar_one_or_none()
        return None if model is None else self._customer(model)

    async def get_customer_by_user(self, user_id: UUID) -> CustomerIdentityData | None:
        model = (
            await self._session.execute(
                select(CustomerModel).where(CustomerModel.user_id == user_id)
            )
        ).scalar_one_or_none()
        return None if model is None else self._customer(model)

    async def get_customer(self, customer_id: UUID) -> CustomerIdentityData | None:
        model = await self._session.get(CustomerModel, customer_id)
        return None if model is None else self._customer(model)

    async def get_role(self, code: str) -> RoleData | None:
        model = (
            await self._session.execute(select(RoleModel).where(RoleModel.code == code))
        ).scalar_one_or_none()
        if model is None or model.id is None:
            return None
        return RoleData(id=model.id, code=model.code, scope=model.scope)

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
        now = utc_now()
        model = UserModel(
            id=uuid4(),
            email=email,
            phone=phone,
            password_hash=password_hash,
            first_name=first_name,
            last_name=last_name,
            account_status="ACTIVE",
            phone_verified_at=verified_at,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        # Flush parents explicitly: these mappings intentionally have no ORM
        # relationships, so dependency order cannot be inferred from objects.
        await self._flush()
        return self._user(model)

    async def add_user_role(self, user_id: UUID, role_id: int) -> None:
        self._session.add(UserRoleModel(user_id=user_id, role_id=role_id))
        await self._flush()

    async def add_customer(
        self,
        *,
        user_id: UUID | None,
        full_name: str,
        phone: str,
        email: str | None,
        verified_at: datetime,
    ) -> CustomerIdentityData:
        now = utc_now()
        model = CustomerModel(
            id=uuid4(),
            user_id=user_id,
            full_name=full_name,
            phone=phone,
            email=email,
            phone_verified_at=verified_at,
            created_at=now,
            updated_at=now,
        )
        self._session.add(model)
        await self._flush()
        return self._customer(model)

    async def promote_customer(
        self,
        customer_id: UUID,
        *,
        user_id: UUID,
        full_name: str,
        email: str | None,
        verified_at: datetime,
    ) -> CustomerIdentityData:
        model = await self._required_customer(customer_id)
        model.user_id = user_id
        model.full_name = full_name
        model.email = email
        model.phone_verified_at = verified_at
        return self._customer(model)

    async def update_guest_name(
        self, customer_id: UUID, *, full_name: str, verified_at: datetime
    ) -> CustomerIdentityData:
        model = await self._required_customer(customer_id)
        model.full_name = full_name
        model.phone_verified_at = verified_at
        return self._customer(model)

    async def _required_customer(self, customer_id: UUID) -> CustomerModel:
        model = await self._session.get(CustomerModel, customer_id)
        if model is None:
            raise AuthDataUnavailableError()
        return model

    async def update_last_login(self, user_id: UUID, *, logged_in_at: datetime) -> None:
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(last_login_at=logged_in_at)
        )

    async def update_password(self, user_id: UUID, password_hash: str) -> None:
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(password_hash=password_hash)
        )

    async def update_phone(
        self,
        user_id: UUID,
        customer_id: UUID,
        *,
        phone: str,
        verified_at: datetime,
    ) -> None:
        # Match customer-profile writes: Customer -> User.
        await self._session.execute(
            select(CustomerModel.id)
            .where(CustomerModel.id == customer_id, CustomerModel.user_id == user_id)
            .with_for_update()
        )
        await self._session.execute(
            select(UserModel.id).where(UserModel.id == user_id).with_for_update()
        )
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == user_id)
            .values(
                phone=phone,
                phone_verified_at=verified_at,
            )
        )
        await self._session.execute(
            update(CustomerModel)
            .where(CustomerModel.id == customer_id)
            .values(
                phone=phone,
                phone_verified_at=verified_at,
            )
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
        self._session.add(
            RefreshTokenModel(
                id=token_id,
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                created_at=created_at,
            )
        )

    async def get_refresh_token_for_update(
        self, token_hash: str
    ) -> RefreshTokenData | None:
        model = (
            await self._session.execute(
                select(RefreshTokenModel)
                .where(RefreshTokenModel.token_hash == token_hash)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return None if model is None else self._refresh(model)

    async def revoke_refresh_token(self, token_id: UUID, revoked_at: datetime) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.id == token_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def revoke_all_refresh_tokens(
        self, user_id: UUID, revoked_at: datetime
    ) -> None:
        await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise self._integrity_error(exc) from None

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise self._integrity_error(exc) from None

    @staticmethod
    def _integrity_error(exc: IntegrityError) -> IdentityConflictError | (
        EmailAlreadyRegisteredError | PhoneAlreadyRegisteredError
    ):
        original = exc.orig
        constraint = getattr(original, "constraint_name", None)
        if constraint is None:
            constraint = getattr(
                getattr(original, "__cause__", None), "constraint_name", None
            )
        if constraint == "uq_users_email":
            return EmailAlreadyRegisteredError()
        if constraint in {"uq_users_phone", "uq_customers_phone"}:
            return PhoneAlreadyRegisteredError()
        return IdentityConflictError()

    async def rollback(self) -> None:
        await self._session.rollback()
