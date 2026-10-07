import io
import re

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlmodel import SQLModel

from app.modules.orders.infrastructure.persistence import models as order_models
from tests.test_phase1_migration import migration_config
from tests.test_phase4_migration import EXPECTED_PHASE_FOUR_TABLES

PHASE_FIVE_INDEXES = {"ix_orders_kitchen_queue", "ix_order_status_history_entry"}


def test_phase5_has_one_linear_head_without_changing_prior_dependencies():
    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_heads() == ["0005_kitchen"]
    assert scripts.get_revision("0005_kitchen").down_revision == "0004_orders"
    assert scripts.get_revision("0004_orders").down_revision == "0003_cart"
    assert len(list(scripts.walk_revisions())) == 5


def test_phase5_creates_only_permissions_role_mappings_and_indexes():
    output = io.StringIO()
    command.upgrade(migration_config(output), "0004_orders:0005_kitchen", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE" not in sql and "ALTER TABLE" not in sql
    assert "KITCHEN_VIEW" in sql and "KITCHEN_MANAGE" in sql
    assert "role.code IN ('ADMIN', 'KITCHEN')" in sql and "role.scope = 'BRANCH'" in sql
    assert "ORDER_MANAGE" not in sql and "ORDER_SETTINGS_MANAGE" not in sql
    assert set(re.findall(r"CREATE INDEX (\w+)", sql)) == PHASE_FIVE_INDEXES
    assert (
        "WHERE status IN ('WAITING', 'PREPARING', 'READY', 'READY_FOR_PICKUP')" in sql
    )
    assert "(order_id, to_status, created_at, id)" in sql
    assert "CREATE EXTENSION" not in sql and "CREATE FUNCTION" not in sql


def test_phase5_downgrade_preserves_every_order_status_and_history():
    output = io.StringIO()
    command.downgrade(migration_config(output), "0005_kitchen:0004_orders", sql=True)
    sql = output.getvalue()
    assert set(re.findall(r"DROP INDEX (\w+)", sql)) == PHASE_FIVE_INDEXES
    assert "DELETE FROM role_permissions" in sql and "DELETE FROM permissions" in sql
    assert "DROP TABLE" not in sql and "ALTER TABLE" not in sql
    assert "UPDATE orders" not in sql and "DELETE FROM order_status_history" not in sql


def test_no_kitchen_tables_or_duplicated_lifecycle_and_metadata_indexes_agree():
    assert order_models
    assert len(SQLModel.metadata.tables) == 34
    assert EXPECTED_PHASE_FOUR_TABLES <= set(SQLModel.metadata.tables)
    assert not any("kitchen" in table for table in SQLModel.metadata.tables)
    indexes = [
        index
        for table in SQLModel.metadata.tables.values()
        for index in table.indexes
        if index.name in PHASE_FIVE_INDEXES
    ]
    assert {index.name for index in indexes} == PHASE_FIVE_INDEXES
    definitions = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for index in indexes
    )
    assert "WHERE status IN" in definitions and "to_status" in definitions


def test_existing_orders_checks_already_cover_preparation_statuses():
    for table in ("orders", "order_status_history"):
        checks = " ".join(
            str(constraint.sqltext)
            for constraint in SQLModel.metadata.tables[table].constraints
            if hasattr(constraint, "sqltext")
        )
        assert all(
            status in checks for status in ("PREPARING", "READY", "READY_FOR_PICKUP")
        )
