from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.infrastructure.config.settings import Settings


@pytest.fixture
def settings() -> Settings:
    # Explicit values take precedence over the developer's environment and .env.
    return Settings(
        _env_file=None,
        app_name="Restaurant App Backend",
        app_env="test",
        app_debug=False,
        app_version="0.1.0",
        api_v1_prefix="/api/v1",
        database_url=None,
        db_host="127.0.0.1",
        db_port=1,
        db_name="foundation_test",
        db_user="test",
        db_password="test-only",
        database_timeout_seconds=0.1,
        cors_origins=["http://localhost:3000"],
    )


@pytest.fixture
def application(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(application: FastAPI) -> Iterator[TestClient]:
    with TestClient(application, raise_server_exceptions=False) as test_client:
        yield test_client
