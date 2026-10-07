import io
import re

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric
from sqlmodel import SQLModel

from app.modules.cart.infrastructure.persistence import models as cart_models
from tests.test_phase1_foundation import EXPECTED_PHASE_ONE_TABLES
from tests.test_phase1_migration import migration_config
from tests.test_phase2_migration import EXPECTED_PHASE_TWO_TABLES

EXPECTED_PHASE_THREE_TABLES = {"carts", "cart_items", "cart_item_addon_options"}


def test_cart_metadata_adds_only_three_tables_and_owns_no_totals_or_branch_items():
    assert cart_models
    assert (
        EXPECTED_PHASE_ONE_TABLES
        | EXPECTED_PHASE_TWO_TABLES
        | EXPECTED_PHASE_THREE_TABLES
        <= set(SQLModel.metadata.tables)
    )
    assert "branch_id" not in SQLModel.metadata.tables["cart_items"].c
    assert not {"subtotal", "total", "charges_total", "discount_total"} & set(
        SQLModel.metadata.tables["carts"].columns.keys()
    )
    assert "line_total" not in SQLModel.metadata.tables["cart_items"].c
    for table in ("cart_items", "cart_item_addon_options"):
        for column in SQLModel.metadata.tables[table].columns:
            if column.name.endswith("_snapshot"):
                assert isinstance(column.type, Numeric) and column.type.asdecimal
                assert column.type.precision == 18 and column.type.scale == 2


def test_cart_revision_remains_linear_with_catalog_unchanged():
    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_revision("0003_cart").down_revision == "0002_catalog"
    assert scripts.get_revision("0002_catalog").down_revision == "0001_phase1"


def test_cart_upgrade_offline_is_scoped_and_reuses_shared_trigger_function():
    output = io.StringIO()
    command.upgrade(migration_config(output), "0002_catalog:0003_cart", sql=True)
    sql = output.getvalue()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == EXPECTED_PHASE_THREE_TABLES
    assert (
        "DROP " not in sql
        and "CREATE FUNCTION" not in sql
        and "CREATE EXTENSION" not in sql
    )
    assert sql.count("restaurant_phase1_set_updated_at()") == 2
    assert "WHERE status = 'ACTIVE'" in sql and "quantity BETWEEN 1 AND 10000" in sql
    assert (
        "unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot"
        in sql
    )
    assert "UNIQUE (cart_item_id, product_addon_option_id)" in sql
    assert "REFERENCES cart_items (id) ON DELETE CASCADE" in sql
    assert "audit_logs" not in sql and "INSERT INTO permissions" not in sql


def test_cart_downgrade_preserves_every_previous_slice():
    output = io.StringIO()
    command.downgrade(migration_config(output), "0003_cart:0002_catalog", sql=True)
    sql = output.getvalue()
    assert set(re.findall(r"DROP TABLE (\w+)", sql)) == EXPECTED_PHASE_THREE_TABLES
    assert "DROP FUNCTION" not in sql and "DROP EXTENSION" not in sql
    assert (
        sql.index("DROP TABLE cart_item_addon_options")
        < sql.index("DROP TABLE cart_items")
        < sql.index("DROP TABLE carts")
    )
    assert "DELETE FROM permissions" not in sql
