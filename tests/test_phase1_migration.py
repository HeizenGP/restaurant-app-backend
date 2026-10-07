import ast
import io
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.test_phase1_foundation import EXPECTED_PHASE_ONE_TABLES

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def migration_config(output: io.StringIO | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


def test_phase_one_revision_remains_the_base_of_the_chain() -> None:
    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_revision("0001_phase1") is not None
    revision = scripts.get_revision("0001_phase1")
    assert revision is not None
    assert revision.down_revision is None


def test_offline_upgrade_creates_only_phase_one_objects_non_destructively() -> None:
    output = io.StringIO()
    command.upgrade(migration_config(output), "0001_phase1", sql=True)
    sql = output.getvalue()
    created = set(re.findall(r"CREATE TABLE (\w+)", sql))

    assert created == EXPECTED_PHASE_ONE_TABLES | {"alembic_version"}
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "DROP EXTENSION" not in sql
    assert "CREATE EXTENSION IF NOT EXISTS citext" in sql
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in sql
    assert "WHERE is_default IS TRUE" in sql
    assert re.search(r"GENERATED ALWAYS AS \(+user_id IS NULL\)+ STORED", sql)
    assert "ON CONFLICT (code) DO UPDATE" in sql
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in sql
    assert "FOR SHARE" in sql
    assert "NEW.updated_at = clock_timestamp()" in sql
    assert "INSERT INTO users" not in sql


def test_offline_downgrade_does_not_remove_shared_extensions() -> None:
    output = io.StringIO()
    command.downgrade(migration_config(output), "0001_phase1:base", sql=True)
    sql = output.getvalue()

    assert "DROP EXTENSION" not in sql
    dropped = re.findall(r"DROP TABLE (\w+)", sql)
    assert set(dropped) == EXPECTED_PHASE_ONE_TABLES
    assert dropped.index("customer_addresses") < dropped.index("customers")
    assert dropped.index("staff_assignments") < dropped.index("branches")
    assert dropped.index("user_roles") < dropped.index("roles")


def test_domain_and_application_do_not_depend_on_external_adapters() -> None:
    forbidden = {
        "fastapi",
        "sqlmodel",
        "sqlalchemy",
        "asyncpg",
        "jwt",
        "pwdlib",
        "pydantic",
    }
    for slice_name in (
        "auth",
        "customers",
        "branches",
        "catalog",
        "cart",
        "orders",
        "kitchen",
        "payments",
        "fulfillment",
    ):
        for layer in ("domain", "application"):
            root = PROJECT_ROOT / "app" / "modules" / slice_name / layer
            for source in root.rglob("*.py"):
                tree = ast.parse(source.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    imports: list[str] = []
                    if isinstance(node, ast.Import):
                        imports = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports = [node.module]
                    for module in imports:
                        assert module.split(".")[0] not in forbidden, source
                        assert ".infrastructure" not in module, source
                        assert ".presentation" not in module, source
