import io
import re

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric
from sqlmodel import SQLModel

from app.modules.catalog.infrastructure.persistence import models as catalog_models
from app.shared.infrastructure.audit import models as audit_models
from tests.test_phase1_foundation import EXPECTED_PHASE_ONE_TABLES
from tests.test_phase1_migration import migration_config

EXPECTED_PHASE_TWO_TABLES = {
    "categories",
    "products",
    "product_images",
    "product_presentations",
    "product_addons",
    "product_addon_options",
    "branch_products",
    "audit_logs",
}


def test_phase_two_metadata_tables_remain_available():
    assert catalog_models and audit_models
    assert EXPECTED_PHASE_ONE_TABLES | EXPECTED_PHASE_TWO_TABLES <= set(
        SQLModel.metadata.tables
    )
    for table, field in (
        ("products", "base_price"),
        ("branch_products", "price_override"),
        ("product_presentations", "price_delta"),
        ("product_addon_options", "additional_price"),
    ):
        column = SQLModel.metadata.tables[table].c[field]
        assert isinstance(column.type, Numeric) and column.type.asdecimal
        assert column.type.precision == 12 and column.type.scale == 2
    assert "branch_id" not in SQLModel.metadata.tables["products"].c


def test_phase_two_revision_keeps_its_predecessor():
    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_revision("0002_catalog").down_revision == "0001_phase1"
    assert scripts.get_revision("0001_phase1").down_revision is None


def test_phase_two_only_upgrade_compiles_non_destructively():
    output = io.StringIO()
    command.upgrade(migration_config(output), "0001_phase1:0002_catalog", sql=True)
    sql = output.getvalue()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == EXPECTED_PHASE_TWO_TABLES
    assert "DROP " not in sql
    assert "CREATE FUNCTION" not in sql
    assert sql.count("restaurant_phase1_set_updated_at()") == 7
    assert "CATALOG_MANAGE" in sql and "STAFF_MANAGE" not in sql
    assert "ON CONFLICT (code) DO NOTHING" in sql
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in sql
    assert "NUMERIC(12, 2)" in sql and "JSONB" in sql
    assert (
        "WHERE is_default IS TRUE AND is_active IS TRUE AND deleted_at IS NULL" in sql
    )
    assert "WHERE is_primary IS TRUE AND deleted_at IS NULL" in sql
    assert "UNIQUE (branch_id, product_id)" in sql


def test_phase_two_downgrade_keeps_phase_one_objects():
    output = io.StringIO()
    command.downgrade(migration_config(output), "0002_catalog:0001_phase1", sql=True)
    sql = output.getvalue()
    assert set(re.findall(r"DROP TABLE (\w+)", sql)) == EXPECTED_PHASE_TWO_TABLES
    assert "DROP FUNCTION" not in sql and "DROP EXTENSION" not in sql
    assert "DELETE FROM permissions WHERE code = 'CATALOG_MANAGE'" in sql
    assert "STAFF_MANAGE" not in sql
    assert sql.index("DROP TABLE products") < sql.index("DROP TABLE categories")
    assert sql.index("DROP TABLE product_addon_options") < sql.index(
        "DROP TABLE product_addons"
    )
