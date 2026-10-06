import logging

from app.shared.infrastructure.config.settings import Settings


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
