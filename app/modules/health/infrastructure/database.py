import asyncio
import logging

from asyncpg import PostgresError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class SQLAlchemyDatabaseProbe:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, timeout: float
    ) -> None:
        self._session_factory = session_factory
        self._timeout = timeout

    async def is_ready(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session_factory() as session:
                    result = await session.execute(text("SELECT 1"))
                    return result.scalar_one() == 1
        except (SQLAlchemyError, PostgresError, OSError, TimeoutError) as exc:
            # Exception messages may contain credentials, SQL or connection details.
            logger.warning("Database readiness check failed (%s)", type(exc).__name__)
            return False
