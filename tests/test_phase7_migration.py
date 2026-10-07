import ast
import io
import re
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from app.modules.fulfillment.infrastructure.persistence import models
from tests.test_phase1_migration import migration_config
from tests.test_phase6_migration import PAYMENT_TABLES, PRIOR_TABLES

FULFILLMENT_TABLES = {"delivery_assignments", "delivery_delay_incidents"}
ROOT = Path(__file__).resolve().parents[1]


def upgrade_sql():
    output = io.StringIO()
    command.upgrade(
        migration_config(output), "0006_payments:0007_fulfillment", sql=True
    )
    return output.getvalue()


def test_phase7_remains_in_the_linear_chain():
    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_revision("0007_fulfillment") is not None
    assert scripts.get_revision("0007_fulfillment").down_revision == "0006_payments"
    assert scripts.get_revision("0006_payments").down_revision == "0005_kitchen"
    assert scripts.get_revision("0001_phase1").down_revision is None


def test_two_operational_tables_only_metadata_has_forty_tables():
    assert models
    assert PRIOR_TABLES | PAYMENT_TABLES | FULFILLMENT_TABLES <= set(
        SQLModel.metadata.tables
    )
    sql = upgrade_sql()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == FULFILLMENT_TABLES
    for forbidden in (
        "CREATE EXTENSION",
        "CREATE FUNCTION",
        "DROP TABLE",
        "UPDATE orders",
        "UPDATE payments",
        "ALTER TABLE orders ADD",
    ):
        assert forbidden not in sql
    assert sql.count("restaurant_phase1_set_updated_at()") == 1


def test_constraints_and_indexes_match_pinned_migration():
    sql = upgrade_sql()
    checks = set(re.findall(r"CONSTRAINT (ck_\w+)", sql))
    expected = {
        c.name
        for table in FULFILLMENT_TABLES
        for c in SQLModel.metadata.tables[table].constraints
        if hasattr(c, "sqltext")
    }
    assert checks == expected
    for name in FULFILLMENT_TABLES:
        table = SQLModel.metadata.tables[name]
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for constraint in table.constraints:
            if hasattr(constraint, "sqltext"):
                assert str(constraint.sqltext) in sql and str(constraint.sqltext) in ddl
        for index in table.indexes:
            assert (
                str(CreateIndex(index).compile(dialect=postgresql.dialect())) + ";"
                in sql
            )
        for fk in table.foreign_keys:
            assert fk.ondelete == "RESTRICT"
        for column in table.columns:
            if column.name.endswith("_at") or column.name == "committed_eta":
                assert column.type.timezone
    assert "CREATE UNIQUE INDEX uq_delivery_assignments_active" in sql
    assert "WHERE unassigned_at IS NULL AND completed_at IS NULL" in sql
    assert "UNIQUE (order_id)" in sql
    assert "delay_threshold_seconds = 900" in sql
    assert "delay_seconds_at_detection > delay_threshold_seconds" in sql


def test_pickup_release_partial_index_and_no_redundant_delivery_queue_index():
    sql = upgrade_sql()
    assert (
        "CREATE INDEX ix_orders_pickup_release ON orders (branch_id, order_number, id)"
        in sql
    )
    assert "mode = 'PICKUP' AND status = 'SCHEDULED' AND payment_status = 'PAID'" in sql
    assert "CREATE INDEX ix_orders_delivery" not in sql
    assert len(re.findall(r"CREATE (?:UNIQUE )?INDEX", sql)) == 6


def test_permissions_admin_branch_only_no_invented_role_or_staff_assignment():
    sql = upgrade_sql()
    for code in (
        "FULFILLMENT_VIEW",
        "FULFILLMENT_MANAGE",
        "DELIVERY_ASSIGN",
        "DELIVERY_DELAY_REVIEW",
    ):
        assert code in sql
    assert "r.code='ADMIN' AND r.scope='BRANCH'" in sql
    assert "KITCHEN" not in sql and "CUSTOMER" not in sql and "DRIVER" not in sql
    assert "INSERT INTO roles" not in sql and "INSERT INTO staff_assignments" not in sql


def test_downgrade_guards_history_before_ddl_and_preserves_orders_payments():
    output = io.StringIO()
    command.downgrade(
        migration_config(output), "0007_fulfillment:0006_payments", sql=True
    )
    sql = output.getvalue()
    assert (
        sql.index("RAISE EXCEPTION") < sql.index("DROP INDEX") < sql.index("DROP TABLE")
    )
    assert "EXISTS (SELECT 1 FROM delivery_assignments)" in sql
    assert "EXISTS (SELECT 1 FROM delivery_delay_incidents)" in sql
    assert set(re.findall(r"DROP TABLE (\w+)", sql)) == FULFILLMENT_TABLES
    for name in PRIOR_TABLES | PAYMENT_TABLES:
        assert "DROP TABLE " + name + ";" not in sql
    assert "DELETE FROM order_status_history" not in sql and "DROP FUNCTION" not in sql


def test_fulfillment_has_no_private_repository_coupling_or_financial_mutation():
    module = ROOT / "app/modules/fulfillment"
    for layer in ("domain", "application"):
        for path in (module / layer).glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [
                n.module
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module
            ]
            assert not any(
                any(
                    part in name
                    for part in (
                        ".catalog.",
                        ".cart.",
                        ".payments.",
                        ".kitchen.",
                        ".infrastructure.",
                        ".presentation.",
                    )
                )
                for name in imports
            )
    source = "\n".join(p.read_text() for p in module.rglob("*.py"))
    for forbidden in (
        "create_all(",
        "._load(",
        "._settings(",
        "PaymentService",
        "KitchenService",
        "refund",
        "coupon",
        "apscheduler",
        "celery",
    ):
        assert forbidden not in source
