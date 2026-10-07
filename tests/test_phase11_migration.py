import ast
import io
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from tests.test_phase1_migration import migration_config

ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "customer_favorites",
    "order_reviews",
    "fiscal_documents",
    "fiscal_document_attempts",
    "roulette_campaigns",
    "roulette_prizes",
    "roulette_participations",
    "roulette_spins",
    "customer_rewards",
}
PERMISSIONS = {
    "REVIEW_VIEW",
    "RECEIPT_VIEW",
    "RECEIPT_MANAGE",
    "PROMOTION_VIEW",
    "PROMOTION_MANAGE",
    "PROMOTION_REDEEM",
}


def upgrade_sql():
    output = io.StringIO()
    command.upgrade(
        migration_config(output), "0010_admin:0011_customer_extras", sql=True
    )
    return output.getvalue()


def test_exact_single_head_eleven_linear_revisions_nine_new_fiftynine_metadata():
    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_heads() == ["0011_customer_extras"]
    assert len(list(scripts.walk_revisions())) == 11
    assert scripts.get_revision("0011_customer_extras").down_revision == "0010_admin"
    sql = upgrade_sql()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == TABLES
    assert len(SQLModel.metadata.tables) == 59
    output = io.StringIO()
    command.upgrade(migration_config(output), "head", sql=True)
    assert set(re.findall(r"CREATE TABLE (\w+)", output.getvalue())) == set(
        SQLModel.metadata.tables
    ) | {"alembic_version"}


@pytest.mark.parametrize("name", sorted(TABLES))
def test_ddl_constraints_indices_restrict_and_timestamp_types_match_metadata(name):
    sql = upgrade_sql()
    table = SQLModel.metadata.tables[name]
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    for constraint in table.constraints:
        if hasattr(constraint, "sqltext"):
            assert str(constraint.sqltext) in sql and str(constraint.sqltext) in ddl
        elif constraint.name and constraint.name.startswith("uq_"):
            assert constraint.name in sql
    for index in table.indexes:
        assert (
            str(CreateIndex(index).compile(dialect=postgresql.dialect())) + ";" in sql
        )
    assert all(fk.ondelete == "RESTRICT" for fk in table.foreign_keys)
    for column in table.columns:
        if column.name.endswith("_at"):
            assert column.type.timezone
    assert table.c.id.primary_key
    assert not any(fk.ondelete == "CASCADE" for fk in table.foreign_keys)


def test_exact_check_constraints_fourteen_indices_integer_decimal_jsonb():
    sql = upgrade_sql()
    checks = {
        c.name
        for name in TABLES
        for c in SQLModel.metadata.tables[name].constraints
        if hasattr(c, "sqltext")
    }
    assert set(re.findall(r"CONSTRAINT (ck_\w+)", sql)) == checks
    assert len(re.findall(r"CREATE (?:UNIQUE )?INDEX", sql)) == 14
    amount = SQLModel.metadata.tables["fiscal_documents"].c.amount.type
    assert amount.precision == 12 and amount.scale == 2 and amount.asdecimal
    assert (
        SQLModel.metadata.tables["roulette_prizes"].c.probability_bps.type.python_type
        is int
    )
    assert (
        SQLModel.metadata.tables[
            "roulette_spins"
        ].c.configuration_snapshot.type.__class__.__name__
        == "JSONB"
    )
    assert "recipient_document_number IS NOT NULL" in sql
    assert "recipient_document_type IS NOT NULL" in sql
    assert "idempotency_key ~ '^[a-f0-9]{64}$'" in sql
    assert "UNIQUE (user_id, product_id)" in sql
    assert "UNIQUE (order_id)" in sql and "UNIQUE (spin_id)" in sql


def test_six_permissions_idempotently_granted_only_official_branch_admin():
    sql = upgrade_sql()
    assert set(re.findall(r"VALUES \('([A-Z_]+)'", sql)) == PERMISSIONS
    assert "ON CONFLICT(code) DO NOTHING" in sql
    assert "ON CONFLICT(role_id,permission_id) DO NOTHING" in sql
    assert "r.code='ADMIN' AND r.scope='BRANCH'" in " ".join(sql.split())
    assert not any(
        word in sql
        for word in ("SUPERADMIN", "KITCHEN", "CUSTOMER' AND", "STAFF_MANAGE")
    )


def test_owned_history_immutable_paid_guard_probability_serialization_and_activation():
    sql = upgrade_sql()
    assert len(re.findall(r"CREATE FUNCTION restaurant_phase11_", sql)) == 5
    assert len(re.findall(r"CREATE TRIGGER ", sql)) == 13
    assert sql.count("restaurant_phase1_set_updated_at()") == 7
    assert "BEFORE UPDATE OR DELETE ON order_reviews" in sql
    assert "BEFORE UPDATE OR DELETE ON roulette_spins" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON fiscal_documents" in " ".join(
        sql.split()
    )
    for value in (
        "o.customer_id=NEW.customer_id",
        "o.branch_id=NEW.branch_id",
        "o.status='SERVED'",
        "o.status='PICKED_UP'",
        "o.status='DELIVERED'",
        "o.payment_status='PAID'",
        "p.status='PAID'",
        "p.amount=NEW.amount",
        "o.total=NEW.amount",
        "FOR SHARE OF o",
        "OLD.status='ISSUED'",
        "WHERE id=NEW.campaign_id FOR UPDATE",
        "IF total>10000",
        "NEW.awarded_count<OLD.awarded_count",
        "Activate only a configured roulette",
    ):
        assert value in sql
    assert (
        "CREATE EXTENSION" not in sql
        and "UPDATE orders SET" not in sql
        and "UPDATE payments SET" not in sql
    )
    assert "ALTER TABLE orders" not in sql and "INSERT INTO users" not in sql


def test_downgrade_guards_all_data_before_any_delete_or_drop():
    output = io.StringIO()
    command.downgrade(
        migration_config(output), "0011_customer_extras:0010_admin", sql=True
    )
    sql = output.getvalue()
    first_delete = sql.index("DELETE FROM role_permissions")
    for table in TABLES:
        guard = sql.index("IF EXISTS(SELECT 1 FROM " + table + ")")
        assert guard < first_delete and guard < sql.index("DROP TABLE")
    assert set(re.findall(r"DROP TABLE (\w+)", sql)) == TABLES
    assert sql.count("RAISE EXCEPTION") == 9
    assert "CASCADE" not in sql and "DROP EXTENSION" not in sql
    assert "DELETE FROM orders" not in sql and "restaurant_phase1_" not in sql
    assert (
        "DROP FUNCTION restaurant_phase10_" not in sql
        and "DROP FUNCTION restaurant_phase9_" not in sql
    )


@pytest.mark.parametrize("slice_", ["favorites", "reviews", "receipts", "promotions"])
def test_slices_hexagonal_business_pure_no_foreign_lifecycle_writes_or_startup_ddl(
    slice_,
):
    base = ROOT / "app/modules" / slice_
    for layer in ("domain", "application"):
        for path in (base / layer).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not any(
                        x in node.module
                        for x in (
                            "sqlalchemy",
                            "sqlmodel",
                            "fastapi",
                            "pydantic",
                            ".infrastructure.",
                            ".presentation.",
                        )
                    )
    source = "\n".join(p.read_text() for p in base.rglob("*.py"))
    for forbidden in (
        "create_all(",
        "ALTER TABLE",
        "CREATE TABLE",
        "UPDATE orders",
        "UPDATE payments",
        "INSERT INTO payments",
        "INSERT INTO carts",
        "notification(",
        "realtime_order_events",
        "FakeFiscal",
        "random.random(",
        "random.choices(",
    ):
        assert forbidden not in source
    assert "async def save(" not in source
