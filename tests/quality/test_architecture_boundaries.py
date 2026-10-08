import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DOMAIN = {
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "sqlmodel",
    "asyncpg",
    "alembic",
}

# Reviewed F10 constant/allowlisted fragments, never bound request values.
# See docs/security-review.md. A new interpolation needs an explicit review.
SQL_FRAGMENTS = {
    "app/modules/customers/infrastructure/persistence/admin_repository.py": {
        "FIELDS",
        "CUSTOMERS_FROM",
        "VISIBLE",
        "search_clause",
        "key",
        "table",
        "condition",
    }
}


def imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "app/modules").glob("*/domain/*.py")),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_domain_is_framework_independent(path):
    assert (
        not {name.split(".")[0] for name in imports(ast.parse(path.read_text()))}
        & FORBIDDEN_DOMAIN
    )


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "app/modules").glob("*/application/*.py")),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_application_uses_ports_not_infrastructure_or_http(path):
    for name in imports(ast.parse(path.read_text())):
        assert ".infrastructure" not in name and ".presentation" not in name
        assert name.split(".")[0] not in FORBIDDEN_DOMAIN


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "app/modules").glob("*/presentation/*.py")),
    ids=lambda p: str(p.relative_to(ROOT)),
)
def test_presentation_does_not_execute_sql(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            assert name not in {"execute", "exec_driver_sql", "commit", "rollback"}


def test_runtime_has_no_ddl_or_unsafe_execution():
    for path in (ROOT / "app").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            assert name not in {"create_all", "drop_all", "eval", "exec", "system"}, (
                path
            )
            if name in {"text", "exec_driver_sql"} and node.args:
                allowed = SQL_FRAGMENTS.get(path.relative_to(ROOT).as_posix(), set())
                for fragment in ast.walk(node.args[0]):
                    if isinstance(fragment, ast.FormattedValue):
                        assert isinstance(fragment.value, ast.Name), path
                        assert fragment.value.id in allowed, path
