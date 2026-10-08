import logging
import traceback

from app.shared.infrastructure.config.settings import Settings


class RedactedServerExceptions(logging.Filter):
    """Uvicorn re-raises handled 500s; never format their exception values."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exception_type, _, frames = record.exc_info
            locations = " -> ".join(
                f"{frame.filename}:{frame.lineno} ({frame.name})"
                for frame in traceback.extract_tb(frames)
            )
            record.msg = "Server exception %s at %s"
            record.args = (
                exception_type.__name__ if exception_type else "UnknownError",
                locations,
            )
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        elif "Traceback (most recent call last)" in record.getMessage():
            # Uvicorn lifespan can log a preformatted ASGI startup.failed message.
            record.msg = "Server lifecycle failure (diagnostic values redacted)"
            record.args = ()
            record.exc_text = None
            record.stack_info = None
        return True


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("app").setLevel(
        logging.DEBUG if settings.app_debug else logging.INFO
    )
    # SQL statements and driver diagnostics must not expose parameters or secrets.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    server = logging.getLogger("uvicorn.error")
    if not any(isinstance(f, RedactedServerExceptions) for f in server.filters):
        server.addFilter(RedactedServerExceptions())
