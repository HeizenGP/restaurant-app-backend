from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from app.main import create_app
from app.modules.health.application.services import HealthService
from app.modules.health.presentation.dependencies import get_health_service
from app.shared.infrastructure.config.settings import Settings


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "service": "Restaurant App Backend",
        "version": "0.1.0",
    }


def test_liveness_never_connects_to_database(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_connection(*args: object, **kwargs: object) -> None:
        pytest.fail("Liveness must not connect to PostgreSQL")

    monkeypatch.setattr(AsyncEngine, "connect", forbidden_connection)

    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("database_ready", [True, False])
def test_readiness_with_dependency_override(
    application: FastAPI, client: TestClient, database_ready: bool
) -> None:
    database = AsyncMock()
    database.is_ready.return_value = database_ready
    service = HealthService("Restaurant App Backend", "0.1.0", database)
    application.dependency_overrides[get_health_service] = lambda: service

    response = client.get("/api/v1/health/ready")

    database.is_ready.assert_awaited_once_with()
    if database_ready:
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "connected"}
    else:
        assert response.status_code == 503
        assert response.json() == {
            "error": {
                "code": "DEPENDENCY_UNAVAILABLE",
                "message": "Database is unavailable",
            }
        }
    application.dependency_overrides.clear()


def test_legacy_root_is_preserved(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Restaurante API", "status": "running"}


def test_configured_service_and_api_prefix(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "app_name": "Configured backend",
            "app_version": "0.2.0",
            "api_v1_prefix": "/custom/v1",
        }
    )
    with TestClient(create_app(configured)) as client:
        response = client.get("/custom/v1/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "Configured backend",
            "version": "0.2.0",
        }
        assert client.get("/api/v1/health").status_code == 404


def test_engine_is_disposed_on_shutdown(
    application: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispose = AsyncMock()
    monkeypatch.setattr(AsyncEngine, "dispose", dispose)

    with TestClient(application):
        assert application.state.database_engine is not None

    dispose.assert_awaited_once()
