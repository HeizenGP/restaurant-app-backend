"""Composition root without a global application or environment read at import."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.lifespan import lifespan
from app.presentation.api.router import create_api_router
from app.presentation.errors import register_exception_handlers
from app.presentation.hardening import HardeningMiddleware
from app.shared.infrastructure.config.settings import Settings, get_settings
from app.shared.infrastructure.logging.config import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    configure_logging(settings)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=False,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(HardeningMiddleware)
    register_exception_handlers(application)
    application.include_router(create_api_router(settings.api_v1_prefix))
    return application
