import ast
import io
import re
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from sqlmodel import SQLModel

from tests.test_phase1_migration import migration_config

ROOT = Path(__file__).resolve().parents[1]
PERMISSIONS = {
    "CUSTOMER_VIEW",
    "CUSTOMER_MANAGE",
    "BRANCH_VIEW",
    "BRANCH_MANAGE",
    "BRANCH_CREATE",
    "DASHBOARD_VIEW",
}


def upgrade_sql():
    output = io.StringIO()
    command.upgrade(migration_config(output), "0009_notifications:0010_admin", sql=True)
    return output.getvalue()


def test_phase10_one_linear_head_zero_new_tables_and_nullable_origin_restrict():
    scripts = ScriptDirectory.from_config(migration_config())
    assert len(scripts.get_heads()) == 1
    assert len(list(scripts.walk_revisions(base="base", head="0010_admin"))) == 10
    assert scripts.get_revision("0010_admin").down_revision == "0009_notifications"
    sql = upgrade_sql()
    assert "CREATE TABLE" not in sql and "DROP TABLE" not in sql
    assert "ADD COLUMN created_by_branch_id UUID" in sql
    assert "REFERENCES branches (id) ON DELETE RESTRICT" in sql
    assert "UPDATE customers" not in sql
    prior_output = io.StringIO()
    command.upgrade(migration_config(prior_output), "0010_admin", sql=True)
    prior_tables = set(re.findall(r"CREATE TABLE (\w+)", prior_output.getvalue())) - {
        "alembic_version"
    }
    assert len(prior_tables) == 50
    assert prior_tables <= set(SQLModel.metadata.tables)
    column = SQLModel.metadata.tables["customers"].c.created_by_branch_id
    assert column.nullable and next(iter(column.foreign_keys)).ondelete == "RESTRICT"


def test_permissions_idempotent_only_branch_admin_no_new_staff_permission():
    sql = upgrade_sql()
    for permission in PERMISSIONS:
        assert "('" + permission + "'" in sql
    assert "ON CONFLICT(code) DO NOTHING" in sql
    assert "ON CONFLICT(role_id,permission_id) DO NOTHING" in sql
    assert "r.code='ADMIN' AND r.scope='BRANCH'" in sql
    assert "STAFF_MANAGE" not in sql and "SUPERADMIN" not in sql
    assert "KITCHEN" not in sql and "CUSTOMER' AND" not in sql


def test_twelve_specific_indexes_match_model_metadata_without_top_product_duplicate():
    sql = upgrade_sql()
    names = set(re.findall(r"CREATE INDEX (\w+)", sql))
    assert len(names) == 12
    indices = {
        i.name: i for table in SQLModel.metadata.tables.values() for i in table.indexes
    }
    for name in names:
        ddl = str(CreateIndex(indices[name]).compile(dialect=postgresql.dialect()))
        assert ddl + ";" in sql
    assert "ix_order_items_order" not in sql


def test_branch_order_concurrency_guard_and_all_pending_operations():
    sql = upgrade_sql()
    for state in (
        "PENDING_PAYMENT",
        "PENDING_CASH_CONFIRMATION",
        "SCHEDULED",
        "WAITING",
        "PREPARING",
        "READY",
        "READY_FOR_PICKUP",
        "OUT_FOR_DELIVERY",
    ):
        assert "'" + state + "'" in sql
    for table in ("refunds", "cancellation_requests", "delivery_assignments"):
        assert "FROM " + table in sql
    assert "FOR SHARE" in sql
    assert "BEFORE INSERT OR UPDATE OF status,branch_id ON orders" in sql
    assert "BEFORE UPDATE OF is_active,deleted_at ON branches" in sql
    assert "LANGUAGE sql VOLATILE" in sql
    assert "UPDATE orders SET" not in sql and "UPDATE payments SET" not in sql
    assert "restaurant_phase9_" not in sql


def test_downgrade_aborts_before_ddl_if_origin_provenance_exists():
    output = io.StringIO()
    command.downgrade(
        migration_config(output), "0010_admin:0009_notifications", sql=True
    )
    sql = output.getvalue()
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP TRIGGER")
    assert "WHERE created_by_branch_id IS NOT NULL" in " ".join(sql.split())
    assert "DROP TABLE" not in sql and "DELETE FROM customers" not in sql
    assert "DROP FUNCTION restaurant_phase9_" not in sql
    assert "DROP FUNCTION restaurant_phase8_" not in sql


def test_admin_domain_and_application_hexagonal_no_sql_http_or_private_slice_calls():
    bases = [ROOT / "app/modules/admin/domain", ROOT / "app/modules/admin/application"]
    bases += [
        ROOT / "app/modules" / slice_ / "application"
        for slice_ in ("customers", "branches")
    ]
    for base in bases:
        paths = base.glob("*.py") if "admin" in base.parts else base.glob("admin_*.py")
        for path in paths:
            source = path.read_text()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not any(
                        part in node.module
                        for part in (
                            "sqlalchemy",
                            "sqlmodel",
                            "fastapi",
                            "starlette",
                            ".infrastructure.",
                            ".presentation.",
                        )
                    )
            assert "._session" not in source
    source = "\n".join(
        p.read_text() for p in (ROOT / "app/modules/admin").rglob("*.py")
    )
    assert "create_all(" not in source and "CREATE TABLE" not in source
    assert "cancel_order(" not in source and "INSERT INTO orders" not in source
