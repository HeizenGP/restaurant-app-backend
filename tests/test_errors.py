import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.application.exceptions import ApplicationError
from app.shared.domain.exceptions import DomainError
from app.shared.infrastructure.config.settings import Settings


@pytest.mark.parametrize(
    ("exception", "status_code", "code", "message"),
    [
        (DomainError("Rule violated"), 409, "DOMAIN_ERROR", "Rule violated"),
        (
            ApplicationError("Invalid operation"),
            400,
            "APPLICATION_ERROR",
            "Invalid operation",
        ),
        (
            RuntimeError("secret-password-token"),
            500,
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred",
        ),
    ],
)
def test_global_errors(
    application: FastAPI,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
    exception: Exception,
    status_code: int,
    code: str,
    message: str,
) -> None:
    @application.get("/test-error")
    async def test_error() -> None:
        raise exception

    with caplog.at_level(logging.ERROR):
        response = client.get("/test-error")

    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code, "message": message}}
    assert "secret-password-token" not in response.text
    assert "secret-password-token" not in caplog.text
    if status_code == 500:
        assert "Unhandled RuntimeError" in caplog.text


def test_debug_mode_does_not_expose_tracebacks(settings: Settings) -> None:
    application = create_app(settings.model_copy(update={"app_debug": True}))

    @application.get("/test-error")
    async def test_error() -> None:
        raise RuntimeError("secret-password-token")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/test-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "secret-password-token" not in response.text
    assert "Traceback" not in response.text


def test_http_error_preserves_headers(application: FastAPI, client: TestClient) -> None:
    @application.get("/test-http-error")
    async def test_http_error() -> None:
        raise HTTPException(
            401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
        )

    response = client.get("/test-http-error")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "HTTP_ERROR"


def test_not_found_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "HTTP_ERROR", "message": "Not Found"}}


def test_validation_does_not_echo_input(
    application: FastAPI, client: TestClient
) -> None:
    @application.get("/test-validation")
    async def test_validation(value: int) -> dict[str, int]:
        return {"value": value}

    response = client.get("/test-validation", params={"value": "secret-password-token"})

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": [{"location": ["query", "value"], "type": "int_parsing"}],
        }
    }
    assert "secret-password-token" not in response.text
