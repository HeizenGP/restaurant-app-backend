from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.shared.infrastructure.config.settings import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Create the single engine owned by the application lifespan."""
    return create_async_engine(
        settings.database_connection_url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_timeout=settings.database_timeout_seconds,
        connect_args={
            "timeout": settings.database_timeout_seconds,
            "command_timeout": settings.database_timeout_seconds,
        },
    )
