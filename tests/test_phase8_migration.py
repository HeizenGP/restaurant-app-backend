import ast
import io
import re
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from app.modules.cancellations.infrastructure.persistence import (
    models as cancellation_models,
)
from app.modules.payments.infrastructure.persistence import refund_models
from tests.test_phase1_migration import migration_config
from tests.test_phase6_migration import PAYMENT_TABLES, PRIOR_TABLES
from tests.test_phase7_migration import FULFILLMENT_TABLES

PHASE8_TABLES = {
    "cancellation_requests",
    "order_cancellations",
    "refunds",
    "refund_attempts",
    "refund_status_history",
    "refund_provider_events",
}
ROOT = Path(__file__).resolve().parents[1]


def upgrade_sql():
    output = io.StringIO()
    command.upgrade(
        migration_config(output),
        "0007_fulfillment:0008_cancellations_refunds",
        sql=True,
    )
    return output.getvalue()


def test_single_linear_head_eight_revisions():
    scripts = ScriptDirectory.from_config(migration_config())
    assert len(scripts.get_heads()) == 1
    revisions = list(scripts.walk_revisions("base", "0008_cancellations_refunds"))
    assert len(revisions) == 8
    assert revisions[0].down_revision == "0007_fulfillment"
    assert scripts.get_revision("0001_phase1").down_revision is None


def test_six_new_tables_exact_metadata_and_no_rewriting_prior_schema():
    assert cancellation_models and refund_models
    historic_tables = PRIOR_TABLES | PAYMENT_TABLES | FULFILLMENT_TABLES | PHASE8_TABLES
    assert historic_tables <= set(SQLModel.metadata.tables)
    assert len(historic_tables) == 46
    sql = upgrade_sql()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == PHASE8_TABLES
    for forbidden in (
        "DROP TABLE",
        "CREATE EXTENSION",
        "UPDATE orders SET",
        "UPDATE payments SET",
        "ALTER TABLE orders ADD",
        "INSERT INTO roles",
        "INSERT INTO staff_assignments",
    ):
        assert forbidden not in sql
    assert sql.count("restaurant_phase1_set_updated_at()") == 3
    assert "CREATE FUNCTION restaurant_phase1_set_updated_at" not in sql


def test_all_constraints_indexes_types_fks_match_pinned_revision():
    sql = upgrade_sql()
    expected = {
        c.name
        for t in PHASE8_TABLES
        for c in SQLModel.metadata.tables[t].constraints
        if hasattr(c, "sqltext")
    }
    assert set(re.findall(r"CONSTRAINT (ck_\w+)", sql)) == expected
    for name in PHASE8_TABLES:
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
        assert all(fk.ondelete == "RESTRICT" for fk in table.foreign_keys)
        assert all(c.type.timezone for c in table.columns if c.name.endswith("_at"))
        for field in ("amount", "reported_amount"):
            if field in table.columns:
                assert table.columns[field].type.asdecimal
                assert (
                    table.columns[field].type.precision == 18
                    and table.columns[field].type.scale == 2
                )
    assert len(re.findall(r"CREATE (?:UNIQUE )?INDEX", sql)) == 10


def test_database_enforces_unique_pending_active_and_full_obligation():
    sql = upgrade_sql()
    for text in (
        "WHERE status = 'PENDING'",
        "WHERE status IN ('CREATED','PROCESSING')",
        "WHERE provider_reference IS NOT NULL",
        "UNIQUE (payment_id)",
        "UNIQUE (order_id)",
        "UNIQUE (refund_id, idempotency_key)",
        "UNIQUE (provider_code, provider_event_id)",
        "evaluated_at IS NOT NULL",
        "amount=current_order.total",
        "amount=paid_payment.amount",
        "payment_id=paid_payment.id",
        "Cancelled order has active fulfillment",
        "Cancelled paid order requires full refund",
        "Original refund obligation is immutable",
    ):
        assert text in sql
    assert sql.count("DEFERRABLE INITIALLY DEFERRED") == 4
    assert "BEFORE UPDATE OR DELETE ON order_cancellations" in sql
    assert "BEFORE UPDATE OR DELETE ON refund_status_history" in sql
    assert "BEFORE UPDATE ON refunds" in sql


def test_permissions_only_existing_admin_branch():
    sql = upgrade_sql()
    for code in ("CANCELLATION_VIEW", "CANCELLATION_MANAGE", "REFUND_MANAGE"):
        assert code in sql
    assert "r.code='ADMIN' AND r.scope='BRANCH'" in sql
    assert "r.code='KITCHEN'" not in sql and "r.code='CUSTOMER'" not in sql


def test_safe_downgrade_checks_every_history_table_before_any_ddl():
    output = io.StringIO()
    command.downgrade(
        migration_config(output),
        "0008_cancellations_refunds:0007_fulfillment",
        sql=True,
    )
    sql = output.getvalue()
    assert (
        sql.index("RAISE EXCEPTION")
        < sql.index("DROP TRIGGER")
        < sql.index("DROP TABLE")
    )
    for name in PHASE8_TABLES:
        assert "EXISTS (SELECT 1 FROM " + name + ")" in sql
    assert set(re.findall(r"DROP TABLE (\w+)", sql)) == PHASE8_TABLES
    assert "DROP FUNCTION restaurant_phase1_set_updated_at" not in sql
    assert "DROP FUNCTION restaurant_phase8_validate_refund()" in sql
    assert "DROP FUNCTION restaurant_phase8_protect_history()" in sql
    assert "DELETE FROM orders" not in sql and "DELETE FROM payments" not in sql


def test_layering_and_no_foreign_private_financial_mutation():
    module = ROOT / "app/modules/cancellations"
    for layer in ("domain", "application"):
        for path in (module / layer).glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [
                n.module
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module
            ]
            assert not any(
                ".infrastructure." in name
                or ".presentation." in name
                or name.startswith(("sqlalchemy", "sqlmodel"))
                for name in imports
            )
    source = "\n".join(p.read_text() for p in module.rglob("*.py"))
    for forbidden in (
        "PaymentService(",
        "KitchenService(",
        "create_all(",
        ".refund(",
        "._load(",
        "._get(",
        "total=",
    ):
        assert forbidden not in source
    payment_source = (ROOT / "app/modules/payments/application/services.py").read_text()
    assert payment_source.count("ensure_cancelled_refund(") == 3
    assert "hasattr(" not in payment_source
