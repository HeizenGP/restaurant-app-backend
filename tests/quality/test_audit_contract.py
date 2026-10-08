import ast
from pathlib import Path

from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder


def test_audit_repository_is_append_only_in_normal_application():
    assert not any(
        name in SQLAlchemyAuditRecorder.__dict__
        for name in ("delete", "update", "remove", "save")
    )
    root = Path(__file__).resolve().parents[2] / "app"
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sql = " ".join(node.value.upper().split())
                assert "DELETE FROM AUDIT_LOGS" not in sql
                assert "UPDATE AUDIT_LOGS" not in sql
