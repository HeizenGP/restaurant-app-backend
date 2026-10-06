import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncpg import InvalidPasswordError
from sqlalchemy.exc import SQLAlchemyError

from app.modules.health.infrastructure.database import SQLAlchemyDatabaseProbe


def test_database_probe_executes_select_and_closes_session() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 1
    session.execute.return_value = result
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=context)

    probe = SQLAlchemyDatabaseProbe(factory, timeout=1)

    assert asyncio.run(probe.is_ready()) is True
    assert str(session.execute.await_args.args[0]) == "SELECT 1"
    context.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "failure_type", [SQLAlchemyError, OSError, TimeoutError, InvalidPasswordError]
)
def test_database_failure_is_safe_and_session_is_closed(
    failure_type: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    session = AsyncMock()
    session.execute.side_effect = failure_type("secret-password-token")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    probe = SQLAlchemyDatabaseProbe(MagicMock(return_value=context), timeout=1)

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(probe.is_ready()) is False

    context.__aexit__.assert_awaited_once()
    assert "Database readiness check failed" in caplog.text
    assert "secret-password-token" not in caplog.text


def test_readiness_timeout_covers_connection_acquisition() -> None:
    async def stalled_connection() -> None:
        await asyncio.sleep(1)

    context = MagicMock()
    context.__aenter__ = AsyncMock(side_effect=stalled_connection)
    probe = SQLAlchemyDatabaseProbe(MagicMock(return_value=context), timeout=0.01)

    assert asyncio.run(probe.is_ready()) is False
