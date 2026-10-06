import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlmodel import SQLModel

from app.shared.infrastructure.config.settings import get_settings
from app.shared.infrastructure.database.engine import create_database_engine
from app.shared.infrastructure.logging.config import configure_logging

# Import future slices' persistence models here before accessing metadata.
# Phase 0 intentionally has no business tables or model imports.
target_metadata = SQLModel.metadata
settings = get_settings()
configure_logging(settings)


def include_name(name: str | None, type_: str, parent_names: dict[str, str]) -> bool:
    if type_ == "table":
        # Existing tables outside SQLModel's ownership must never be dropped by
        # autogenerate while the restaurant schema is adopted slice by slice.
        return parent_names["schema_qualified_table_name"] in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_connection_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
