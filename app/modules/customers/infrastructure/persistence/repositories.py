from types import TracebackType
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.infrastructure.persistence.models import UserModel
from app.modules.customers.application.dtos import (
    Address,
    AddressCreate,
    AddressUpdate,
    CustomerProfile,
    ProfileUpdate,
)
from app.modules.customers.application.exceptions import EmailAlreadyRegisteredError
from app.modules.customers.infrastructure.persistence.models import (
    CustomerAddressModel,
    CustomerModel,
)
from app.shared.application.exceptions import ConflictError, DependencyUnavailableError


class SQLAlchemyCustomerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_profile(
        self, customer_id: UUID, *, user_id: UUID | None
    ) -> CustomerProfile | None:
        statement = select(CustomerModel).where(CustomerModel.id == customer_id)
        if user_id is None:
            statement = statement.where(CustomerModel.user_id.is_(None))
        else:
            statement = statement.where(CustomerModel.user_id == user_id)
        customer = (await self._session.execute(statement)).scalar_one_or_none()
        if customer is None:
            return None
        user = None
        if user_id is not None:
            user = await self._session.get(UserModel, user_id)
            if user is None:
                return None
        return _to_profile(customer, user)

    async def email_is_registered(self, email: str, *, excluding: UUID) -> bool:
        statement = select(UserModel.id).where(
            UserModel.email == email,
            UserModel.id != excluding,
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def update_guest_profile(
        self, customer_id: UUID, *, full_name: str
    ) -> CustomerProfile | None:
        statement = (
            select(CustomerModel)
            .where(
                CustomerModel.id == customer_id,
                CustomerModel.user_id.is_(None),
            )
            .with_for_update()
        )
        customer = (await self._session.execute(statement)).scalar_one_or_none()
        if customer is None:
            return None
        customer.full_name = full_name
        await self._session.flush()
        return _to_profile(customer, None)

    async def update_registered_profile(
        self,
        customer_id: UUID,
        user_id: UUID,
        profile_update: ProfileUpdate,
    ) -> CustomerProfile | None:
        customer_statement = (
            select(CustomerModel)
            .where(
                CustomerModel.id == customer_id,
                CustomerModel.user_id == user_id,
            )
            .with_for_update()
        )
        customer = (
            await self._session.execute(customer_statement)
        ).scalar_one_or_none()
        if customer is None:
            return None
        user_statement = (
            select(UserModel).where(UserModel.id == user_id).with_for_update()
        )
        user = (await self._session.execute(user_statement)).scalar_one_or_none()
        if user is None:
            return None

        if "first_name" in profile_update.provided_fields:
            user.first_name = _required(profile_update.first_name)
        if "last_name" in profile_update.provided_fields:
            user.last_name = profile_update.last_name
        if "email" in profile_update.provided_fields:
            if user.email != profile_update.email:
                user.email_verified_at = None
            user.email = profile_update.email
            customer.email = profile_update.email
        customer.full_name = " ".join(
            part for part in (user.first_name, user.last_name) if part
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            if "email" in profile_update.provided_fields and _is_unique_violation(exc):
                raise EmailAlreadyRegisteredError from None
            raise
        return _to_profile(customer, user)

    async def list_addresses(self, customer_id: UUID) -> list[Address]:
        statement = (
            select(CustomerAddressModel)
            .where(CustomerAddressModel.customer_id == customer_id)
            .order_by(
                CustomerAddressModel.is_default.desc(),
                CustomerAddressModel.created_at.asc(),
                CustomerAddressModel.id.asc(),
            )
        )
        addresses = (await self._session.execute(statement)).scalars().all()
        return [_to_address(address) for address in addresses]

    async def create_address(
        self, customer_id: UUID, address: AddressCreate
    ) -> Address:
        model = CustomerAddressModel(
            customer_id=customer_id,
            label=address.label,
            recipient_name=address.recipient_name,
            recipient_phone=address.recipient_phone,
            address_line=address.address_line,
            reference_text=address.reference_text,
            district=address.district,
            city=address.city,
            department=address.department,
            latitude=address.latitude,
            longitude=address.longitude,
            is_default=address.is_default,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_address(model)

    async def update_address(
        self,
        customer_id: UUID,
        address_id: UUID,
        address_update: AddressUpdate,
    ) -> Address | None:
        statement = (
            select(CustomerAddressModel)
            .where(
                CustomerAddressModel.id == address_id,
                CustomerAddressModel.customer_id == customer_id,
            )
            .with_for_update()
        )
        address = (await self._session.execute(statement)).scalar_one_or_none()
        if address is None:
            return None
        for field in address_update.provided_fields:
            setattr(address, field, getattr(address_update, field))
        await self._session.flush()
        return _to_address(address)

    async def delete_address(self, customer_id: UUID, address_id: UUID) -> bool:
        statement = (
            select(CustomerAddressModel)
            .where(
                CustomerAddressModel.id == address_id,
                CustomerAddressModel.customer_id == customer_id,
            )
            .with_for_update()
        )
        address = (await self._session.execute(statement)).scalar_one_or_none()
        if address is None:
            return False
        await self._session.delete(address)
        await self._session.flush()
        return True

    async def unset_default_address(
        self, customer_id: UUID, *, keeping: UUID | None = None
    ) -> None:
        # Serialize default changes per customer. The partial unique index remains
        # the final barrier, while this lock gives concurrent requests a stable order.
        lock = (
            select(CustomerModel.id)
            .where(CustomerModel.id == customer_id)
            .with_for_update()
        )
        await self._session.execute(lock)
        statement = sql_update(CustomerAddressModel).where(
            CustomerAddressModel.customer_id == customer_id,
            CustomerAddressModel.is_default.is_(True),
        )
        if keeping is not None:
            statement = statement.where(CustomerAddressModel.id != keeping)
        await self._session.execute(
            statement.values(is_default=False).execution_options(
                synchronize_session=False
            )
        )


class SQLAlchemyCustomerUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.customers: SQLAlchemyCustomerRepository

    async def __aenter__(self) -> "SQLAlchemyCustomerUnitOfWork":
        self._session = self._session_factory()
        self.customers = SQLAlchemyCustomerRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if exc_type is not None:
                await session.rollback()
        finally:
            await session.close()
            self._session = None
        if isinstance(exc, IntegrityError):
            raise ConflictError("Operation conflicts with existing data") from None
        if isinstance(exc, (SQLAlchemyError, OSError, TimeoutError)):
            raise DependencyUnavailableError("Database is unavailable") from None

    async def commit(self) -> None:
        await self._require_session().commit()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Customer unit of work is not active")
        return self._session


def _to_profile(customer: CustomerModel, user: UserModel | None) -> CustomerProfile:
    return CustomerProfile(
        id=customer.id,
        full_name=customer.full_name,
        first_name=user.first_name if user is not None else None,
        last_name=user.last_name if user is not None else None,
        email=user.email if user is not None else customer.email,
        phone=customer.phone,
        phone_verified=customer.phone_verified_at is not None,
        is_guest=customer.user_id is None,
    )


def _to_address(address: CustomerAddressModel) -> Address:
    return Address(
        id=address.id,
        label=address.label,
        recipient_name=address.recipient_name,
        recipient_phone=address.recipient_phone,
        address_line=address.address_line,
        reference_text=address.reference_text,
        district=address.district,
        city=address.city,
        department=address.department,
        latitude=address.latitude,
        longitude=address.longitude,
        is_default=address.is_default,
    )


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("required profile value is missing")
    return value


def _is_unique_violation(exc: IntegrityError) -> bool:
    candidates = (exc.orig, getattr(exc.orig, "__cause__", None))
    for candidate in candidates:
        if candidate is None:
            continue
        sqlstate = getattr(candidate, "sqlstate", None)
        if sqlstate is None:
            sqlstate = getattr(candidate, "pgcode", None)
        if sqlstate == "23505":
            return True
    return False
