"""Phase 10 administration: permissions, optional customer origin, read indexes and
branch gate.

Revision ID: 0010_admin
Revises: 0009_notifications
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0010_admin"
down_revision = "0009_notifications"
branch_labels = None
depends_on = None

PERMISSIONS = (
    "CUSTOMER_VIEW",
    "CUSTOMER_MANAGE",
    "BRANCH_VIEW",
    "BRANCH_MANAGE",
    "BRANCH_CREATE",
    "DASHBOARD_VIEW",
)
INDEXES = (
    (
        "ix_customers_admin_origin",
        "customers",
        ["created_by_branch_id", "created_at", "id"],
    ),
    ("ix_orders_admin_branch_created", "orders", ["branch_id", "created_at", "id"]),
    ("ix_orders_admin_customer_branch", "orders", ["customer_id", "branch_id"]),
    ("ix_payments_admin_paid", "payments", ["status", "paid_at", "order_id"]),
    ("ix_refunds_admin_refunded", "refunds", ["status", "refunded_at", "order_id"]),
)
PREFIX_INDEXES = (
    (
        "ix_customers_admin_name_prefix",
        "customers",
        "lower(full_name) text_pattern_ops",
    ),
    (
        "ix_customers_admin_email_prefix",
        "customers",
        "lower(email::text) text_pattern_ops",
    ),
    ("ix_customers_admin_phone_prefix", "customers", "phone varchar_pattern_ops"),
    (
        "ix_users_staff_name_prefix",
        "users",
        "lower(first_name || ' ' || coalesce(last_name,'')) text_pattern_ops",
    ),
    ("ix_users_staff_lastname_prefix", "users", "lower(last_name) text_pattern_ops"),
    ("ix_users_staff_email_prefix", "users", "lower(email::text) text_pattern_ops"),
    ("ix_users_staff_phone_prefix", "users", "phone varchar_pattern_ops"),
)


def upgrade():
    op.add_column(
        "customers",
        sa.Column("created_by_branch_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_customers_admin_origin",
        "customers",
        "branches",
        ["created_by_branch_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)
    for name, table, expression in PREFIX_INDEXES:
        op.execute(f"CREATE INDEX {name} ON {table} ({expression})")
    for code in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO permissions(code,name,description) VALUES "
                f"('{code}','{code}','Branch-scoped administration') ON "
                f"CONFLICT(code) DO NOTHING"
            )
        )
    codes = ",".join("'" + p + "'" for p in PERMISSIONS)
    op.execute(
        "INSERT INTO role_permissions(role_id,permission_id) "
        "SELECT r.id,p.id FROM roles r JOIN permissions p ON p.code IN (" + codes + ") "
        "WHERE r.code='ADMIN' AND r.scope='BRANCH' ON CONFLICT(role_id,"
        "permission_id) DO NOTHING"
    )
    op.execute("""
        CREATE FUNCTION restaurant_phase10_branch_busy(p_branch uuid)
        RETURNS boolean LANGUAGE sql VOLATILE AS $$
            SELECT EXISTS(SELECT 1 FROM orders WHERE branch_id=p_branch AND status IN
                ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION','SCHEDULED','WAITING',
                 'PREPARING','READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY'))
            OR EXISTS(SELECT 1 FROM refunds r JOIN orders o ON o.id=r.order_id
                WHERE o.branch_id=p_branch
                AND r.status IN ('PENDING','PROCESSING','FAILED'))
            OR EXISTS(SELECT 1 FROM payments p JOIN orders o ON o.id=p.order_id
                WHERE o.branch_id=p_branch
                AND (p.status='PROCESSING' OR p.reconciliation_required))
            OR EXISTS(SELECT 1 FROM payment_attempts a JOIN payments p ON
            p.id=a.payment_id
                JOIN orders o ON o.id=p.order_id WHERE o.branch_id=p_branch
                AND a.status IN ('CREATED','PROCESSING'))
            OR EXISTS(SELECT 1 FROM cancellation_requests c
                WHERE c.branch_id=p_branch AND c.status='PENDING')
            OR EXISTS(SELECT 1 FROM delivery_assignments d JOIN orders o ON
            o.id=d.order_id
                WHERE o.branch_id=p_branch AND d.unassigned_at IS NULL AND
                d.completed_at IS NULL)
        $$
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase10_deactivate_branch()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.is_active AND (NOT NEW.is_active OR NEW.deleted_at IS NOT NULL)
                AND restaurant_phase10_branch_busy(OLD.id) THEN
                RAISE EXCEPTION 'Branch has active operations' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_phase10_branch_deactivate BEFORE UPDATE OF is_active,"
        "deleted_at ON branches "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase10_deactivate_branch()"
    )
    op.execute("""
        CREATE FUNCTION restaurant_phase10_order_branch_gate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE branch_active boolean;
        BEGIN
            IF TG_OP='UPDATE' THEN
                IF OLD.branch_id=NEW.branch_id AND OLD.status IN
                    ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION','SCHEDULED','WAITING',
                     'PREPARING','READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY') THEN
                    RETURN NEW;
                END IF;
            END IF;
            IF NEW.status IN
                ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION','SCHEDULED','WAITING',
                 'PREPARING','READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY') THEN
                SELECT is_active AND deleted_at IS NULL INTO branch_active
                    FROM branches WHERE id=NEW.branch_id FOR SHARE;
                IF branch_active IS DISTINCT FROM true THEN
                    RAISE EXCEPTION 'Branch is inactive' USING ERRCODE='23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_phase10_order_branch_gate BEFORE INSERT OR UPDATE OF "
        "status,branch_id ON orders "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase10_order_branch_gate()"
    )

    op.execute("""
        CREATE FUNCTION restaurant_phase10_consistent_timezone()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target uuid;
        BEGIN
            IF TG_OP='UPDATE' THEN
                IF NEW.timezone IS NOT DISTINCT FROM OLD.timezone THEN
                    RETURN NULL;
                END IF;
            END IF;
            IF TG_TABLE_NAME='branches' THEN target:=NEW.id;
            ELSE target:=NEW.branch_id;
            END IF;
            IF EXISTS(SELECT 1 FROM branches b JOIN branch_order_settings s
                ON s.branch_id=b.id WHERE b.id=target AND b.timezone<>s.timezone)
            THEN
                RAISE EXCEPTION 'Branch and order settings clocks must agree'
                    USING ERRCODE='23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in ("branches", "branch_order_settings"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_phase10_{table}_timezone "
            f"AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION restaurant_phase10_consistent_timezone()"
        )


def downgrade():
    # Origin is provenance, not branch ownership. Never delete customers to downgrade.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS(SELECT 1 FROM customers WHERE created_by_branch_id IS NOT
            NULL) THEN
                RAISE EXCEPTION 'Phase 10 origin provenance exists; downgrade
                requires an explicit preservation decision';
            END IF;
        END $$
    """)
    for table in ("branches", "branch_order_settings"):
        op.execute(f"DROP TRIGGER trg_phase10_{table}_timezone ON {table}")
    op.execute("DROP FUNCTION restaurant_phase10_consistent_timezone()")
    op.execute("DROP TRIGGER trg_phase10_order_branch_gate ON orders")
    op.execute("DROP TRIGGER trg_phase10_branch_deactivate ON branches")
    op.execute("DROP FUNCTION restaurant_phase10_order_branch_gate()")
    op.execute("DROP FUNCTION restaurant_phase10_deactivate_branch()")
    op.execute("DROP FUNCTION restaurant_phase10_branch_busy(uuid)")
    codes = ",".join("'" + p + "'" for p in PERMISSIONS)
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM "
        "permissions WHERE code IN (" + codes + "))"
    )
    op.execute("DELETE FROM permissions WHERE code IN (" + codes + ")")
    for name, table, _ in reversed(INDEXES + PREFIX_INDEXES):
        op.drop_index(name, table_name=table)
    op.drop_constraint("fk_customers_admin_origin", "customers", type_="foreignkey")
    op.drop_column("customers", "created_by_branch_id")
