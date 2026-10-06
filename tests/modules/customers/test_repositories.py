import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.infrastructure.persistence.models import UserModel
from app.modules.customers.application.dtos import ProfileUpdate
from app.modules.customers.application.exceptions import EmailAlreadyRegisteredError
from app.modules.customers.infrastructure.persistence.models import CustomerModel
from app.modules.customers.infrastructure.persistence.repositories import (
    SQLAlchemyCustomerRepository,
    SQLAlchemyCustomerUnitOfWork,
)
from app.shared.domain.time import utc_now


def _registered_models() -> tuple[CustomerModel, UserModel]:
    user_id = uuid4()
    user = UserModel(
        id=user_id,
        email="ana@example.com",
        phone="+51987654321",
        password_hash="safe-hash",
        first_name="Ana",
        last_name="Ruiz",
    )
    customer = CustomerModel(
        user_id=user_id,
        full_name="Ana Ruiz",
        phone="+51987654321",
        email="ana@example.com",
    )
    return customer, user


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def test_repository_updates_user_and_customer_in_one_session() -> None:
    customer, user = _registered_models()
    user.email_verified_at = utc_now()
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=[_scalar_result(customer), _scalar_result(user)]
    )
    session.flush = AsyncMock()
    repository = SQLAlchemyCustomerRepository(session)
    update = ProfileUpdate(
        provided_fields=frozenset({"first_name", "last_name", "email"}),
        first_name="Elena",
        last_name=None,
        email="elena@example.com",
    )

    profile = asyncio.run(
        repository.update_registered_profile(customer.id, user.id, update)
    )

    assert profile is not None
    assert user.first_name == "Elena"
    assert user.last_name is None
    assert user.email == "elena@example.com"
    assert user.email_verified_at is None
    assert customer.full_name == "Elena"
    assert customer.email == user.email
    session.flush.assert_awaited_once_with()
    assert not hasattr(session, "commit") or session.commit.await_count == 0


class _UniqueViolation(Exception):
    sqlstate = "23505"


def test_repository_translates_email_integrity_error_without_leaking_value() -> None:
    customer, user = _registered_models()
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=[_scalar_result(customer), _scalar_result(user)]
    )
    session.flush = AsyncMock(
        side_effect=IntegrityError("users insert", {}, _UniqueViolation("private"))
    )
    repository = SQLAlchemyCustomerRepository(session)
    update = ProfileUpdate(
        provided_fields=frozenset({"email"}), email="used@example.com"
    )

    with pytest.raises(EmailAlreadyRegisteredError) as captured:
        asyncio.run(repository.update_registered_profile(customer.id, user.id, update))

    assert captured.value.code == "EMAIL_ALREADY_REGISTERED"
    assert "used@example.com" not in str(captured.value)
    assert captured.value.__cause__ is None


def test_unit_of_work_rolls_back_and_closes_on_failure() -> None:
    session = MagicMock(spec=AsyncSession)
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session_factory = MagicMock(return_value=session)
    unit_of_work = SQLAlchemyCustomerUnitOfWork(session_factory)

    async def fail_inside_transaction() -> None:
        with pytest.raises(RuntimeError):
            async with unit_of_work:
                raise RuntimeError("expected test failure")

    asyncio.run(fail_inside_transaction())

    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()


def test_unit_of_work_is_the_only_commit_boundary() -> None:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.close = AsyncMock()
    unit_of_work = SQLAlchemyCustomerUnitOfWork(MagicMock(return_value=session))

    async def commit_transaction() -> None:
        async with unit_of_work:
            await unit_of_work.commit()

    asyncio.run(commit_transaction())

    session.commit.assert_awaited_once_with()
    session.close.assert_awaited_once_with()
