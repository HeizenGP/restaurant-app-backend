"""Payment ledger, attempts and verified-provider audit.
Revision ID: 0006_payments
Revises: 0005_kitchen
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_payments"
down_revision = "0005_kitchen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("method_type", sa.String(8), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency_code",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'PEN'"),
        ),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reconciliation_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("order_id", name="uq_payments_order"),
        sa.CheckConstraint(
            "method_type IN ('CASH','ONLINE')", name="ck_payments_method"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','PAID','FAILED')",
            name="ck_payments_status",
        ),
        sa.CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric", name="ck_payments_amount"
        ),
        sa.CheckConstraint("currency_code = 'PEN'", name="ck_payments_currency"),
        sa.CheckConstraint(
            "(status = 'PAID') = (paid_at IS NOT NULL)", name="ck_payments_paid_at"
        ),
        sa.CheckConstraint(
            "method_type <> 'CASH' OR status IN ('PENDING','PAID')",
            name="ck_payments_cash_state",
        ),
    )
    op.create_table(
        "payment_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'CREATED'")
        ),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("client_action_kind", sa.String(16), nullable=True),
        sa.Column("client_action_value", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "payment_id", "idempotency_key", name="uq_payment_attempts_key"
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name="ck_payment_attempts_key",
        ),
        sa.CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_payment_attempts_provider",
        ),
        sa.CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric",
            name="ck_payment_attempts_amount",
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_payment_attempts_status",
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED')) = (completed_at IS NOT NULL)",
            name="ck_payment_attempts_completed",
        ),
        sa.CheckConstraint(
            "status NOT IN ('PROCESSING','SUCCEEDED') "
            "OR provider_reference IS NOT NULL",
            name="ck_payment_attempts_reference_required",
        ),
        sa.CheckConstraint(
            "provider_reference IS NULL OR (length(provider_reference) BETWEEN "
            "1 AND 255 AND provider_reference = btrim(provider_reference))",
            name="ck_payment_attempts_reference",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR (status = 'FAILED' AND failure_code ~ "
            "'^[A-Z][A-Z0-9_]{0,63}$')",
            name="ck_payment_attempts_failure",
        ),
        sa.CheckConstraint(
            "(client_action_kind IS NULL AND client_action_value IS NULL) OR "
            "(client_action_kind IS NOT NULL AND client_action_value IS NOT "
            "NULL AND client_action_kind IN ('REDIRECT','SDK_TOKEN') AND "
            "status = 'PROCESSING' AND length(client_action_value) BETWEEN 1 "
            "AND 2048)",
            name="ck_payment_attempts_action",
        ),
    )
    op.create_index(
        "uq_payment_attempts_reference",
        "payment_attempts",
        ["provider_code", "provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )
    op.create_index(
        "uq_payment_attempts_active",
        "payment_attempts",
        ["payment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CREATED','PROCESSING')"),
    )
    op.create_index(
        "ix_payment_attempts_recent",
        "payment_attempts",
        ["payment_id", "created_at", "id"],
    )
    op.create_table(
        "payment_status_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "payment_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("provider_event_id", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "to_status IN ('PENDING','PROCESSING','PAID','FAILED') AND "
            "(from_status IS NULL OR from_status IN "
            "('PENDING','PROCESSING','PAID','FAILED'))",
            name="ck_payment_status_history_states",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_payment_status_history_change",
        ),
        sa.CheckConstraint(
            "source IN ('CUSTOMER','PROVIDER','STAFF','SYSTEM')",
            name="ck_payment_status_history_source",
        ),
        sa.CheckConstraint(
            "source <> 'STAFF' OR changed_by_user_id IS NOT NULL",
            name="ck_payment_status_history_staff",
        ),
        sa.CheckConstraint(
            "source NOT IN ('PROVIDER','SYSTEM') OR changed_by_user_id IS NULL",
            name="ck_payment_status_history_service_actor",
        ),
        sa.CheckConstraint(
            "from_status IS NOT NULL OR (to_status = 'PENDING' AND source IN "
            "('SYSTEM','CUSTOMER'))",
            name="ck_payment_status_history_initial",
        ),
    )
    op.create_index(
        "ix_payment_status_history_recent",
        "payment_status_history",
        ["payment_id", "created_at", "id"],
    )
    op.create_table(
        "payment_provider_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(200), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reported_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reported_currency", sa.String(3), nullable=False),
        sa.Column(
            "provider_occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("event_type", sa.String(80), nullable=True),
        sa.Column(
            "processing_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'RECEIVED'"),
        ),
        sa.Column(
            "payment_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "provider_code", "provider_event_id", name="uq_payment_provider_events_key"
        ),
        sa.CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_payment_provider_events_provider",
        ),
        sa.CheckConstraint(
            "length(provider_event_id) BETWEEN 1 AND 200 AND provider_event_id "
            "= btrim(provider_event_id)",
            name="ck_payment_provider_events_id",
        ),
        sa.CheckConstraint(
            "length(provider_reference) BETWEEN 1 AND 255 AND "
            "provider_reference = btrim(provider_reference)",
            name="ck_payment_provider_events_reference",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[a-f0-9]{64}$'", name="ck_payment_provider_events_hash"
        ),
        sa.CheckConstraint(
            "result IN ('SUCCEEDED','FAILED')", name="ck_payment_provider_events_result"
        ),
        sa.CheckConstraint(
            "reported_amount >= 0 AND reported_amount <> 'NaN'::numeric",
            name="ck_payment_provider_events_amount",
        ),
        sa.CheckConstraint(
            "reported_currency ~ '^[A-Z]{3}$'",
            name="ck_payment_provider_events_currency",
        ),
        sa.CheckConstraint(
            "processing_status IN ('RECEIVED','PROCESSED','IGNORED','REJECTED')",
            name="ck_payment_provider_events_status",
        ),
        sa.CheckConstraint(
            "(processing_status = 'RECEIVED') = (processed_at IS NULL)",
            name="ck_payment_provider_events_processed",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_payment_provider_events_reason",
        ),
    )
    op.create_index(
        "ix_payment_provider_events_processing",
        "payment_provider_events",
        ["processing_status", "received_at", "id"],
    )
    for table in ("payments", "payment_attempts"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION restaurant_phase1_set_updated_at()"
        )
    op.execute("""
        INSERT INTO permissions(code, name, description)
        VALUES ('PAYMENT_CASH_MANAGE', 'Confirm branch cash payment',
                'Record actual receipt of cash for a local order')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions(role_id, permission_id)
        SELECT role.id, permission.id FROM roles role
        JOIN permissions permission ON permission.code = 'PAYMENT_CASH_MANAGE'
        WHERE role.code = 'ADMIN' AND role.scope = 'BRANCH'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """)


def downgrade() -> None:
    # A financial ledger cannot be silently erased by a schema rollback.
    # Abort BEFORE any DDL; an empty isolated test schema may be rolled back.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM payments) OR
               EXISTS (SELECT 1 FROM payment_provider_events) THEN
                RAISE EXCEPTION 'Payment ledger is nonempty; preserve and reconcile it';
            END IF;
        END $$
    """)
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions WHERE code = 'PAYMENT_CASH_MANAGE')
    """)
    op.execute("DELETE FROM permissions WHERE code = 'PAYMENT_CASH_MANAGE'")
    for table in ("payments", "payment_attempts"):
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
    op.drop_table("payment_provider_events")
    op.drop_table("payment_status_history")
    op.drop_table("payment_attempts")
    op.drop_table("payments")
