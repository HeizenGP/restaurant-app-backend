import logging
import sys

from app.shared.infrastructure.config.settings import Settings
from app.shared.infrastructure.logging.config import configure_logging


def test_uvicorn_exception_tracebacks_do_not_leak_values(caplog):
    settings = Settings(_env_file=None, app_env="test")
    configure_logging(settings)
    configure_logging(settings)
    server = logging.getLogger("uvicorn.error")
    assert (
        sum(type(f).__name__ == "RedactedServerExceptions" for f in server.filters) == 1
    )
    try:
        raise RuntimeError("TEST_SENTINEL_PASSWORD_BODY_DSN_OTP_TOKEN")
    except RuntimeError:
        with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
            server.error("Exception in ASGI application", exc_info=sys.exc_info())
            server.error(
                "Traceback (most recent call last):\n"
                "RuntimeError: TEST_SENTINEL_PASSWORD_BODY_DSN_OTP_TOKEN"
            )
    assert "TEST_SENTINEL" not in caplog.text
    assert "Server exception RuntimeError" in caplog.text
    assert "test_server_logging.py" in caplog.text
    assert "Server lifecycle failure" in caplog.text
    assert all(not r.exc_info and not r.exc_text for r in caplog.records)
