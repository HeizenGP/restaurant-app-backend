import ast
import io
import re
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from app.modules.notifications.infrastructure.persistence import models
from tests.test_phase1_migration import migration_config
from tests.test_phase6_migration import PAYMENT_TABLES, PRIOR_TABLES
from tests.test_phase7_migration import FULFILLMENT_TABLES
from tests.test_phase8_migration import PHASE8_TABLES

PHASE9_TABLES = {
    "realtime_order_events",
    "customer_notifications",
    "notification_devices",
    "notification_push_deliveries",
}
ROOT = Path(__file__).resolve().parents[1]


def upgrade_sql():
    output = io.StringIO()
    command.upgrade(
        migration_config(output),
        "0008_cancellations_refunds:0009_notifications",
        sql=True,
    )
    return output.getvalue()


def test_single_head_nine_linear_revisions_exact_fifty_metadata_tables():
    assert models
    scripts = ScriptDirectory.from_config(migration_config())
    assert len(scripts.get_heads()) == 1
    revisions = list(scripts.walk_revisions(base="base", head="0009_notifications"))
    assert len(revisions) == 9
    assert revisions[0].down_revision == "0008_cancellations_refunds"
    assert scripts.get_revision("0001_phase1").down_revision is None
    historic_tables = (
        PRIOR_TABLES
        | PAYMENT_TABLES
        | FULFILLMENT_TABLES
        | PHASE8_TABLES
        | PHASE9_TABLES
    )
    assert len(historic_tables) == 50
    assert historic_tables <= set(SQLModel.metadata.tables)
    prior_output = io.StringIO()
    command.upgrade(migration_config(prior_output), "0009_notifications", sql=True)
    assert set(
        re.findall(r"CREATE TABLE (\w+)", prior_output.getvalue())
    ) == historic_tables | {"alembic_version"}


def test_pinned_four_tables_nine_indexes_constraints_and_identity_match_metadata():
    sql = upgrade_sql()
    assert set(re.findall(r"CREATE TABLE (\w+)", sql)) == PHASE9_TABLES
    expected = {
        c.name
        for name in PHASE9_TABLES
        for c in SQLModel.metadata.tables[name].constraints
        if hasattr(c, "sqltext")
    }
    assert set(re.findall(r"CONSTRAINT (ck_\w+)", sql)) == expected
    assert len(re.findall(r"CREATE (?:UNIQUE )?INDEX", sql)) == 9
    assert sql.count("GENERATED ALWAYS AS IDENTITY") == 2
    assert "sequence_id DESC" in sql
    for name in PHASE9_TABLES:
        table = SQLModel.metadata.tables[name]
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        for constraint in table.constraints:
            if hasattr(constraint, "sqltext"):
                assert str(constraint.sqltext) in sql
                assert str(constraint.sqltext) in ddl
        for index in table.indexes:
            assert (
                str(CreateIndex(index).compile(dialect=postgresql.dialect())) + ";"
                in sql
            )
        assert all(fk.ondelete == "RESTRICT" for fk in table.foreign_keys)
        assert all(
            c.type.timezone for c in table.columns if c.name.endswith(("_at", "_until"))
        )
    assert "UNIQUE (source_kind, source_id, kind)" in sql
    assert "UNIQUE (notification_id, device_id)" in sql
    assert "UNIQUE (provider_code, push_token)" in sql


def test_rf53_history_capture_is_exact_and_rf26_separate():
    sql = upgrade_sql()
    history = sql.split("CREATE FUNCTION restaurant_phase9_history_notification")[
        1
    ].split("CREATE FUNCTION restaurant_phase9_delay_notification")[0]
    for value in (
        "NEW.from_status IS NULL",
        "NEW.from_status=NEW.to_status",
        "NEW.to_status='PREPARING'",
        "NEW.to_status='READY'",
        "NEW.to_status='READY_FOR_PICKUP'",
        "NEW.to_status='OUT_FOR_DELIVERY'",
        "NEW.to_status='DELIVERED'",
        "current_order.mode='PICKUP'",
        "current_order.mode='DELIVERY'",
        "NEW.id,NEW.created_at",
    ):
        assert value in history
    for forbidden in (
        "ORDER_CANCELLED",
        "ORDER_PAID",
        "ORDER_SERVED",
        "ORDER_PICKED_UP",
        "ORDER_WAITING",
        "ORDER_SCHEDULED",
        "ORDER BY",
        "LIMIT 1",
    ):
        assert forbidden not in history
    assert "'ORDER_RECEIVED',NEW.status" in sql
    assert "'DELIVERY_DELAY_INCIDENT'" in sql and "NEW.id,NEW.detected_at" in sql


def test_capture_commit_order_gate_before_ids_and_dedupe_checks_fact_not_corruption():
    sql = upgrade_sql()
    assert "pg_advisory_xact_lock(907009001::bigint)" in sql
    for start, target in (
        ("restaurant_phase9_order_event", "INSERT INTO realtime_order_events"),
        ("restaurant_phase9_notification(", "INSERT INTO customer_notifications"),
        ("restaurant_phase9_delay_notification", "INSERT INTO realtime_order_events"),
    ):
        body = sql.split("CREATE FUNCTION " + start)[1]
        assert body.index("PERFORM restaurant_phase9_cursor_gate()") < body.index(
            target
        )
    assert (
        "ON CONFLICT ON CONSTRAINT uq_customer_notifications_source DO NOTHING" in sql
    )
    assert "Notification source conflicts with historical fact" in sql
    assert "AND created_at=p_occurred" in sql
    assert "AND order_status IS NOT DISTINCT FROM p_status" in sql


def test_atomic_capture_device_share_lock_no_backfill_or_http_or_foreign_writes():
    sql = upgrade_sql()
    assert len(re.findall(r"CREATE FUNCTION restaurant_phase9_", sql)) == 7
    assert len(re.findall(r"CREATE TRIGGER ", sql)) == 9
    assert "AFTER UPDATE OF status,payment_status ON orders" in sql
    assert "AFTER INSERT ON order_status_history" in sql
    assert "AFTER INSERT ON delivery_delay_incidents" in sql
    assert "AFTER INSERT ON customer_notifications" in sql
    assert "WHERE d.customer_id=NEW.customer_id AND d.is_active" in sql
    assert "FOR SHARE OF d" in sql
    assert sql.count("restaurant_phase1_set_updated_at()") == 2
    for forbidden in (
        "CREATE FUNCTION restaurant_phase1_",
        "CREATE EXTENSION",
        "ALTER TABLE orders",
        "INSERT INTO order_status_history",
        "UPDATE orders SET",
        "UPDATE payments SET",
        "DELETE FROM orders",
        "http_post",
        "CREATE TABLE kitchen_",
        "UPDATE refunds",
        "INSERT INTO customer_notifications SELECT",
    ):
        assert forbidden not in sql


def test_only_admin_branch_gets_new_realtime_permission_no_superadmin():
    sql = upgrade_sql()
    assert "ORDER_REALTIME_VIEW" in sql
    assert "r.code='ADMIN' AND r.scope='BRANCH'" in sql
    assert "r.code='KITCHEN'" not in sql and "r.code='CUSTOMER'" not in sql
    assert "SUPERADMIN" not in sql


def test_append_only_and_first_read_immutable_in_database():
    sql = upgrade_sql()
    for text in (
        "BEFORE UPDATE OR DELETE ON realtime_order_events",
        "BEFORE UPDATE OR DELETE ON customer_notifications",
        "to_jsonb(NEW)-'read_at'",
        "OLD.read_at IS NOT NULL",
        "OLD.read_at IS DISTINCT FROM NEW.read_at",
        "Notification/realtime history is append-only",
    ):
        assert text in sql


def test_guarded_downgrade_checks_all_four_before_ddl_only_own_objects():
    out = io.StringIO()
    command.downgrade(
        migration_config(out), "0009_notifications:0008_cancellations_refunds", sql=True
    )
    sql = out.getvalue()
    assert (
        sql.index("RAISE EXCEPTION")
        < sql.index("DROP TRIGGER")
        < sql.index("DROP TABLE")
    )
    assert set(re.findall(r"DROP TABLE (\w+)", sql)) == PHASE9_TABLES
    for table in PHASE9_TABLES:
        assert "EXISTS (SELECT 1 FROM " + table + ")" in sql
    assert "DROP FUNCTION restaurant_phase1_" not in sql
    assert "DROP FUNCTION restaurant_phase8_" not in sql
    assert "DELETE FROM orders" not in sql


def test_hexagonal_boundaries_and_no_business_service_dependency_or_worker_loop():
    base = ROOT / "app/modules/notifications"
    for layer in ("domain", "application"):
        for path in (base / layer).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not any(
                        x in node.module
                        for x in (
                            ".infrastructure.",
                            ".presentation.",
                            "sqlalchemy",
                            "sqlmodel",
                            "fastapi",
                            "starlette",
                        )
                    )
    for slice_ in ("orders", "payments", "kitchen", "fulfillment", "cancellations"):
        for path in (ROOT / "app/modules" / slice_).rglob("*.py"):
            assert "modules.notifications" not in path.read_text()
    source = "\n".join(p.read_text() for p in base.rglob("*.py"))
    for forbidden in (
        "create_all(",
        "firebase_admin",
        "apns2",
        "celery",
        "APScheduler",
        "PaymentService(",
        "KitchenService(",
        "FulfillmentService(",
    ):
        assert forbidden not in source
    lifespan = (ROOT / "app/lifespan.py").read_text()
    assert "notifications" not in lifespan and "push" not in lifespan
