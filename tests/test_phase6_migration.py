import ast
import io
import re
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from app.modules.payments.infrastructure.persistence import models as payment_models
from tests.test_phase1_foundation import EXPECTED_PHASE_ONE_TABLES
from tests.test_phase1_migration import migration_config
from tests.test_phase2_migration import EXPECTED_PHASE_TWO_TABLES
from tests.test_phase3_migration import EXPECTED_PHASE_THREE_TABLES
from tests.test_phase4_migration import EXPECTED_PHASE_FOUR_TABLES

PAYMENT_TABLES = {
    "payments",
    "payment_attempts",
    "payment_status_history",
    "payment_provider_events",
}
PRIOR_TABLES = (
    EXPECTED_PHASE_ONE_TABLES
    | EXPECTED_PHASE_TWO_TABLES
    | EXPECTED_PHASE_THREE_TABLES
    | EXPECTED_PHASE_FOUR_TABLES
)
ROOT = Path(__file__).resolve().parents[1]


def upgrade_sql():
    output = io.StringIO()
    command.upgrade(migration_config(output), "0005_kitchen:0006_payments", sql=True)
    return output.getvalue()


def test_phase6_is_the_sole_linear_head():
    script = ScriptDirectory.from_config(migration_config())
    assert script.get_heads() == ["0006_payments"]
    assert script.get_revision("0006_payments").down_revision == "0005_kitchen"
    assert len(list(script.walk_revisions())) == 6


def test_current_metadata_contains_four_new_financial_tables():
    assert payment_models
    assert set(SQLModel.metadata.tables) == PRIOR_TABLES | PAYMENT_TABLES
    assert len(SQLModel.metadata.tables) == 38
    for name, column in (
        ("payments", "amount"),
        ("payment_attempts", "amount"),
        ("payment_provider_events", "reported_amount"),
    ):
        value = SQLModel.metadata.tables[name].c[column]
        assert isinstance(value.type, Numeric) and value.type.asdecimal
        assert (value.type.precision, value.type.scale) == (18, 2)
    for name in PAYMENT_TABLES:
        for column in SQLModel.metadata.tables[name].columns:
            if column.name.endswith("_at"):
                assert column.type.timezone
        for fk in SQLModel.metadata.tables[name].foreign_keys:
            assert fk.ondelete == "RESTRICT"


def test_migration_has_payment_attempt_and_provider_race_barriers():
    sql = upgrade_sql()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == PAYMENT_TABLES
    assert "UNIQUE (order_id)" in sql and "UNIQUE (payment_id, idempotency_key)" in sql
    assert "UNIQUE (provider_code, provider_event_id)" in sql
    assert "CREATE UNIQUE INDEX uq_payment_attempts_active" in sql
    assert "WHERE status IN ('CREATED','PROCESSING')" in sql
    assert "WHERE provider_reference IS NOT NULL" in sql
    assert "currency_code = 'PEN'" in sql and "NaN" in sql
    assert sql.count("restaurant_phase1_set_updated_at()") == 2
    assert all(
        word not in sql
        for word in (
            "CREATE EXTENSION",
            "CREATE FUNCTION",
            "DROP TABLE",
            "UPDATE orders",
        )
    )


def test_metadata_constraints_and_indexes_match_pinned_migration():
    sql = upgrade_sql()
    checks = set(re.findall(r"CONSTRAINT (ck_\w+)", sql))
    indexes = set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", sql))
    expected_checks = {
        c.name
        for name in PAYMENT_TABLES
        for c in SQLModel.metadata.tables[name].constraints
        if hasattr(c, "sqltext")
    }
    expected_indexes = {
        i.name
        for name in PAYMENT_TABLES
        for i in SQLModel.metadata.tables[name].indexes
    }
    assert checks == expected_checks and indexes == expected_indexes
    for name in PAYMENT_TABLES:
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


def test_only_branch_admin_gets_cash_permission_not_kitchen_or_customer():
    sql = upgrade_sql()
    assert "PAYMENT_CASH_MANAGE" in sql
    assert "role.code = 'ADMIN' AND role.scope = 'BRANCH'" in sql
    assert (
        "KITCHEN" not in sql
        and "CUSTOMER" not in sql.split("INSERT INTO permissions")[1]
    )
    assert "PAYMENT_VIEW" not in sql


def test_downgrade_refuses_nonempty_financial_audit_before_ddl_and_preserves_orders():
    output = io.StringIO()
    command.downgrade(migration_config(output), "0006_payments:0005_kitchen", sql=True)
    sql = output.getvalue()
    assert (
        sql.index("RAISE EXCEPTION")
        < sql.index("DROP TRIGGER")
        < sql.index("DROP TABLE")
    )
    assert (
        "EXISTS (SELECT 1 FROM payments)" in sql
        and "EXISTS (SELECT 1 FROM payment_provider_events)" in sql
    )
    dropped = re.findall(r"DROP TABLE (\w+)", sql)
    assert dropped == [
        "payment_provider_events",
        "payment_status_history",
        "payment_attempts",
        "payments",
    ]
    for name in PRIOR_TABLES:
        assert "DROP TABLE " + name + ";" not in sql
    assert "DROP EXTENSION" not in sql and "DROP FUNCTION" not in sql


def test_payments_does_not_import_cart_catalog_kitchen_or_private_order_repository():
    for layer in ("domain", "application"):
        for path in (ROOT / "app/modules/payments" / layer).glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = [
                n.module
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module
            ]
            assert not any(
                ".cart." in i or ".catalog." in i or ".kitchen." in i for i in imports
            )
    source = "\n".join(
        p.read_text() for p in (ROOT / "app/modules/payments").rglob("*.py")
    )
    for forbidden in (
        "SQLAlchemyOrderRepository",
        "create_all(",
        "FakeGateway",
        "TestGateway",
        "_load(",
    ):
        assert forbidden not in source
