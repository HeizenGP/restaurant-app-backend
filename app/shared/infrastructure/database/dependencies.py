from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.application.exceptions import ConflictError, DependencyUnavailableError


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one session per request; each use case controls its transaction."""
    session_factory: async_sessionmaker[AsyncSession] = (
        request.app.state.session_factory
    )
    async with session_factory() as session:
        try:
            yield session
        except IntegrityError:
            await session.rollback()
            raise ConflictError("Operation conflicts with existing data") from None
        except (SQLAlchemyError, OSError, TimeoutError):
            await session.rollback()
            raise DependencyUnavailableError("Database is unavailable") from None
