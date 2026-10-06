from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_allowed_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_unconfigured_origin_is_rejected(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_receives_cors_headers_even_on_internal_error(
    application: FastAPI,
    client: TestClient,
) -> None:
    @application.get("/cors-internal-error")
    async def internal_error() -> None:
        raise RuntimeError("test-only-private-detail")

    response = client.get(
        "/cors-internal-error", headers={"Origin": "http://localhost:3000"}
    )
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "test-only-private-detail" not in response.text
    untrusted = client.get(
        "/cors-internal-error", headers={"Origin": "https://untrusted.example"}
    )
    assert "access-control-allow-origin" not in untrusted.headers
