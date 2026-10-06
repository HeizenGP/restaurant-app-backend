import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.modules.health.application.services import HealthService
from app.modules.health.infrastructure.database import SQLAlchemyDatabaseProbe
from app.shared.infrastructure.database.engine import create_database_engine
from app.shared.infrastructure.database.session import create_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = application.state.settings
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    application.state.database_engine = engine
    application.state.session_factory = session_factory
    application.state.health_service = HealthService(
        service=settings.app_name,
        version=settings.app_version,
        database=SQLAlchemyDatabaseProbe(
            session_factory, timeout=settings.database_timeout_seconds
        ),
    )
    logger.info("Backend started (environment=%s)", settings.app_env)
    try:
        yield
    finally:
        await engine.dispose()
        logger.info("Backend stopped; database pool disposed")
