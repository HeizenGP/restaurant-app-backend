"""Explicit opt-in only; all schema changes roll back in a caller-owned transaction."""

import asyncio
import os

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import URL, Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.shared.infrastructure.config.settings import get_settings
from tests.test_phase1_foundation import EXPECTED_PHASE_ONE_TABLES
from tests.test_phase1_migration import migration_config

pytestmark = pytest.mark.integration


def guarded_test_url(request: pytest.FixtureRequest) -> URL:
    if request.config.getoption("markexpr") not in {
        "integration",
        "performance",
        "integration and e2e",
        "integration and performance",
    }:
        pytest.skip("Opt-in PostgreSQL test: run pytest -m integration")
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        if os.environ.get("REQUIRE_POSTGRES_INTEGRATION") == "1":
            pytest.fail(
                "CI requires TEST_DATABASE_URL; skipping is not success", pytrace=False
            )
        pytest.skip("TEST_DATABASE_URL is not configured")
    try:
        url = make_url(raw)
    except Exception:
        pytest.fail("TEST_DATABASE_URL is not a valid database URL", pytrace=False)
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        pytest.fail("Integration tests require PostgreSQL", pytrace=False)
    database_name = (url.database or "").lower()
    if not url.host or any(
        marker in database_name for marker in ("production", "prod", "staging")
    ):
        pytest.fail("A TEST-only PostgreSQL host/database is required", pytrace=False)
    if not (
        database_name.startswith("test_")
        or database_name.endswith("_test")
        or "_test_" in database_name
    ):
        pytest.fail(
            "Use a dedicated database whose name includes a test marker", pytrace=False
        )
    normal = get_settings().database_connection_url
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    same_host = url.host == normal.host or {url.host, normal.host} <= local_hosts
    if (
        same_host
        and (url.port or 5432) == (normal.port or 5432)
        and url.database == normal.database
    ):
        pytest.fail(
            "TEST_DATABASE_URL must not identify the normal database", pytrace=False
        )
    return url.set(drivername="postgresql+asyncpg")


def migrate_and_inspect(connection: Connection) -> None:
    config = migration_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "0001_phase1")
    inspector = inspect(connection)
    assert set(inspector.get_table_names()) == EXPECTED_PHASE_ONE_TABLES | {
        "alembic_version"
    }
    for name in EXPECTED_PHASE_ONE_TABLES:
        assert inspector.get_pk_constraint(name)["constrained_columns"]
    assert (
        connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0001_phase1"
    )
    assert dict(connection.execute(text("SELECT code, scope FROM roles")).all()) == {
        "CUSTOMER": "GLOBAL",
        "ADMIN": "BRANCH",
        "KITCHEN": "BRANCH",
    }
    assert connection.scalars(text("SELECT code FROM permissions")).all() == [
        "STAFF_MANAGE"
    ]
    assert connection.scalar(text("SELECT count(*) FROM users")) == 0
    indexes = inspector.get_indexes("customer_addresses")
    assert any(
        index["name"] == "uq_customer_addresses_one_default" and index["unique"]
        for index in indexes
    )
    generated = next(
        column
        for column in inspector.get_columns("customers")
        if column["name"] == "is_guest"
    )
    assert generated["computed"]["persisted"] is True


def test_upgrade_in_clean_dedicated_database_is_transactional(
    request: pytest.FixtureRequest,
) -> None:
    url = guarded_test_url(request)

    async def verify() -> None:
        engine = create_async_engine(url, echo=False, connect_args={"timeout": 5})
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    objects = await connection.execute(
                        text(
                            "SELECT n.nspname, c.relname FROM pg_class c "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
                            "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                            "AND n.nspname NOT LIKE 'pg_toast%'"
                        )
                    )
                    if objects.first() is not None:
                        pytest.fail(
                            "Migration test requires a clean, empty database; "
                            "no existing objects are modified",
                            pytrace=False,
                        )
                    await connection.run_sync(migrate_and_inspect)
                finally:
                    await transaction.rollback()
                remaining = await connection.run_sync(
                    lambda sync: inspect(sync).get_table_names()
                )
                assert remaining == []
        finally:
            await engine.dispose()

    asyncio.run(verify())
