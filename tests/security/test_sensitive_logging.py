import logging
from uuid import UUID

import pytest
from fastapi.responses import StreamingResponse

from app.presentation.hardening import SECURITY_HEADERS


@pytest.mark.parametrize(
    "path,status", [("/api/v1/health", 200), ("/missing", 404), ("/api/v1/orders", 401)]
)
def test_security_headers_on_success_and_errors(client, path, status):
    result = client.get(path, headers={"X-Request-ID": "test-request-12"})
    assert result.status_code == status
    assert result.headers["x-request-id"] == "test-request-12"
    for key, value in SECURITY_HEADERS.items():
        assert result.headers[key] == value


def test_unhandled_error_headers_and_logs_never_echo_secrets(
    application, client, caplog
):
    secret = "PHASE12_PRIVATE_SENTINEL"

    @application.post("/security-probe")
    async def probe():
        raise RuntimeError(secret)

    with caplog.at_level(logging.INFO, logger="app"):
        result = client.post(
            "/security-probe?password=" + secret,
            headers={
                "Authorization": "Bearer " + secret,
                "X-Request-ID": "invalid whitespace",
            },
            json={"otp": secret, "password": secret},
        )
    assert result.status_code == 500
    UUID(result.headers["x-request-id"])
    application_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("app.")
    )
    # httpx2's TEST client logs its own URL; deployed Uvicorn access logging
    # must be disabled/redacted as documented in the release runbook.
    assert secret not in application_logs and secret not in result.text
    assert "Unhandled RuntimeError" in caplog.text
    for key, value in SECURITY_HEADERS.items():
        assert result.headers[key] == value


def test_stream_is_not_buffered_and_keeps_sse_headers(application, client):
    @application.get("/security-stream")
    async def stream():
        async def body():
            yield "event: test\ndata: safe\n\n"

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = client.get("/security-stream")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.text == "event: test\ndata: safe\n\n"


def test_cors_allows_browser_sse_resume_and_correlation(client):
    response = client.options(
        "/api/v1/notifications/stream",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": (
                "Authorization,Last-Event-ID,X-Request-ID"
            ),
        },
    )
    assert response.status_code == 200
