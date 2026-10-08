import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import lifespan as lifecycle
from scripts.contracts import contract_app


def test_partial_startup_failure_disposes_pool_without_ddl(monkeypatch):
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(lifecycle, "create_database_engine", lambda _: engine)

    def broken_factory(_):
        raise RuntimeError("TEST startup failure")

    monkeypatch.setattr(lifecycle, "create_session_factory", broken_factory)

    async def scenario():
        with pytest.raises(RuntimeError, match="TEST startup failure"):
            async with lifecycle.lifespan(contract_app()):
                pytest.fail("Startup must not yield after a failure")

    asyncio.run(scenario())
    engine.dispose.assert_awaited_once()
