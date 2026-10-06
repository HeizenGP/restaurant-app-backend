import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement

from app.modules.auth.application.errors import (
    EmailAlreadyRegisteredError,
    IdentityConflictError,
    PhoneAlreadyRegisteredError,
)
from app.modules.auth.domain.models import OtpPurpose
from app.modules.auth.infrastructure.persistence.models import RefreshTokenModel
from app.modules.auth.infrastructure.persistence.repositories import (
    SQLAlchemyAuthRepository,
)
from app.shared.domain.time import utc_now


def make_session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session


def sql(statement: ClauseElement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_otp_locks_phone_and_purpose_even_before_a_challenge_exists() -> None:
    session = make_session()
    repository = SQLAlchemyAuthRepository(session)

    result = asyncio.run(
        repository.latest_otp("+51999999001", OtpPurpose.REGISTER, lock=True)
    )

    assert result is None
    advisory, row = session.execute.await_args_list
    assert "pg_advisory_xact_lock(hashtextextended" in str(advisory.args[0])
    assert advisory.args[1] == {"key": "otp:+51999999001:REGISTER"}
    query = sql(row.args[0])
    assert "FOR UPDATE" in query
    assert "ORDER BY otp_challenges.created_at DESC" in query
    assert "+51999999001" not in query


def test_unlocked_otp_read_does_not_acquire_advisory_lock() -> None:
    session = make_session()
    asyncio.run(
        SQLAlchemyAuthRepository(session).latest_otp(
            "+51999999001", OtpPurpose.REGISTER
        )
    )

    session.execute.assert_awaited_once()
    assert "FOR UPDATE" not in sql(session.execute.await_args.args[0])


def test_refresh_lookup_locks_row_and_uses_only_the_token_hash() -> None:
    session = make_session()
    token_hash = "e" * 64
    asyncio.run(
        SQLAlchemyAuthRepository(session).get_refresh_token_for_update(token_hash)
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "FOR UPDATE" in str(compiled)
    assert compiled.params["token_hash_1"] == token_hash
    assert token_hash not in str(compiled)


def test_login_locks_current_user_during_password_verification() -> None:
    session = make_session()
    asyncio.run(
        SQLAlchemyAuthRepository(session).get_user_by_identifier("test@example.test")
    )

    assert "FOR UPDATE" in sql(session.execute.await_args.args[0])


def test_parent_and_child_inserts_flush_without_committing() -> None:
    session = make_session()
    repository = SQLAlchemyAuthRepository(session)

    async def create_identity() -> None:
        user = await repository.add_user(
            email=None,
            phone="+51999999001",
            password_hash="test-only-hash-placeholder",
            first_name="Prueba",
            last_name=None,
            verified_at=utc_now(),
        )
        await repository.add_user_role(user.id, 1)
        await repository.add_customer(
            user_id=user.id,
            full_name="Prueba",
            phone="+51999999001",
            email=None,
            verified_at=utc_now(),
        )

    asyncio.run(create_identity())
    assert session.flush.await_count == 3
    session.commit.assert_not_awaited()


def test_refresh_storage_contains_only_hash_not_plaintext_token() -> None:
    session = make_session()
    now = utc_now()
    asyncio.run(
        SQLAlchemyAuthRepository(session).add_refresh_token(
            token_id=uuid4(),
            user_id=uuid4(),
            token_hash="e" * 64,
            expires_at=now + timedelta(days=1),
            created_at=now,
        )
    )
    model = session.add.call_args.args[0]
    assert isinstance(model, RefreshTokenModel)
    assert model.token_hash == "e" * 64
    assert not hasattr(model, "refresh_token")
    session.commit.assert_not_awaited()


class ConstraintViolation(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("sensitive rejected database values")
        self.constraint_name = constraint_name


@pytest.mark.parametrize(
    ("constraint", "expected_error"),
    [
        ("uq_users_email", EmailAlreadyRegisteredError),
        ("uq_users_phone", PhoneAlreadyRegisteredError),
        ("uq_customers_phone", PhoneAlreadyRegisteredError),
        ("unknown_constraint", IdentityConflictError),
    ],
)
def test_commit_integrity_errors_are_safe_and_roll_back(
    constraint: str, expected_error: type[Exception]
) -> None:
    session = make_session()
    session.commit.side_effect = IntegrityError(
        "sensitive SQL",
        {"secret": "sensitive parameters"},
        ConstraintViolation(constraint),
    )
    with pytest.raises(expected_error) as raised:
        asyncio.run(SQLAlchemyAuthRepository(session).commit())

    session.rollback.assert_awaited_once()
    assert "sensitive" not in str(raised.value)
    assert raised.value.__suppress_context__
