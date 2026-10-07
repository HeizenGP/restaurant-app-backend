"""Cancellation and full refund histories, invariants and branch permissions.
Revision ID: 0008_cancellations_refunds
Revises: 0007_fulfillment
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_cancellations_refunds"
down_revision = "0007_fulfillment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cancellation_requests",
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
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "evaluated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluation_note", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED')",
            name="ck_cancellation_requests_status",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 1000 AND reason !~ '[<>[:cntrl:]]'",
            name="ck_cancellation_requests_reason",
        ),
        sa.CheckConstraint(
            "evaluation_note IS NULL OR (length(btrim(evaluation_note)) BETWEEN 1 AND "
            "2000 AND evaluation_note !~ '[<>[:cntrl:]]')",
            name="ck_cancellation_requests_note",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND evaluated_by_user_id IS NULL AND evaluated_at IS "
            "NULL AND evaluation_note IS NULL) OR (status IN ('APPROVED','REJECTED') "
            "AND evaluated_by_user_id IS NOT NULL AND evaluated_at IS NOT NULL AND "
            "evaluated_at >= requested_at)",
            name="ck_cancellation_requests_evaluation",
        ),
    )
    op.create_index(
        "uq_cancellation_requests_pending",
        "cancellation_requests",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_cancellation_requests_owner",
        "cancellation_requests",
        ["customer_id", "order_id", "requested_at", "id"],
    )
    op.create_index(
        "ix_cancellation_requests_review",
        "cancellation_requests",
        ["branch_id", "status", "requested_at", "id"],
    )
    op.create_table(
        "order_cancellations",
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
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cancellation_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cancellation_requests.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column(
            "cancelled_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source IN ('ADMIN','CUSTOMER_REQUEST')",
            name="ck_order_cancellations_source",
        ),
        sa.CheckConstraint(
            "reason_code IN ('OUT_OF_STOCK','OTHER','CUSTOMER_REQUEST')",
            name="ck_order_cancellations_reason",
        ),
        sa.CheckConstraint(
            "(source = 'CUSTOMER_REQUEST' AND cancellation_request_id IS NOT NULL AND "
            "reason_code = 'CUSTOMER_REQUEST') OR (source = 'ADMIN' AND reason_code "
            "IN ('OUT_OF_STOCK','OTHER') AND cancellation_request_id IS NULL)",
            name="ck_order_cancellations_provenance",
        ),
        sa.CheckConstraint(
            "(reason_code <> 'OTHER' OR reason_text IS NOT NULL) AND (reason_text IS "
            "NULL OR (length(btrim(reason_text)) BETWEEN 1 AND 1000 AND reason_text "
            "!~ '[<>[:cntrl:]]'))",
            name="ck_order_cancellations_text",
        ),
        sa.UniqueConstraint("order_id", name="uq_order_cancellations_order"),
        sa.UniqueConstraint(
            "cancellation_request_id", name="uq_order_cancellations_request"
        ),
    )
    op.create_index(
        "ix_order_cancellations_branch",
        "order_cancellations",
        ["branch_id", "cancelled_at", "id"],
    )
    op.create_table(
        "refunds",
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
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency_code",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'PEN'"),
        ),
        sa.Column("method_type", sa.String(8), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column(
            "reason_code",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'CANCELLATION'"),
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric", name="ck_refunds_amount"
        ),
        sa.CheckConstraint(
            "method_type IN ('CASH','ONLINE')", name="ck_refunds_method"
        ),
        sa.CheckConstraint("currency_code = 'PEN'", name="ck_refunds_currency"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','REFUNDED','FAILED')",
            name="ck_refunds_status",
        ),
        sa.CheckConstraint("reason_code = 'CANCELLATION'", name="ck_refunds_reason"),
        sa.CheckConstraint(
            "(status = 'REFUNDED') = (refunded_at IS NOT NULL)",
            name="ck_refunds_refunded_at",
        ),
        sa.CheckConstraint(
            "refunded_at IS NULL OR refunded_at >= requested_at", name="ck_refunds_time"
        ),
        sa.CheckConstraint(
            "method_type <> 'CASH' OR status IN ('PENDING','REFUNDED')",
            name="ck_refunds_cash_state",
        ),
        sa.UniqueConstraint("payment_id", name="uq_refunds_payment"),
        sa.UniqueConstraint("order_id", name="uq_refunds_order"),
    )
    op.create_index("ix_refunds_queue", "refunds", ["status", "requested_at", "id"])
    op.create_index("ix_refunds_recent", "refunds", ["requested_at", "id"])
    op.create_table(
        "refund_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "refund_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refunds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'CREATED'")
        ),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
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
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name="ck_refund_attempts_key",
        ),
        sa.CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_refund_attempts_provider",
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_refund_attempts_status",
        ),
        sa.CheckConstraint(
            "amount >= 0 AND amount <> 'NaN'::numeric", name="ck_refund_attempts_amount"
        ),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED')) = (completed_at IS NOT NULL)",
            name="ck_refund_attempts_completed",
        ),
        sa.CheckConstraint(
            "status NOT IN ('PROCESSING','SUCCEEDED') OR provider_reference IS NOT "
            "NULL",
            name="ck_refund_attempts_reference",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR (status = 'FAILED' AND failure_code ~ "
            "'^[A-Z][A-Z0-9_]{0,63}$')",
            name="ck_refund_attempts_failure",
        ),
        sa.UniqueConstraint(
            "refund_id", "idempotency_key", name="uq_refund_attempts_key"
        ),
    )
    op.create_index(
        "uq_refund_attempts_active",
        "refund_attempts",
        ["refund_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('CREATED','PROCESSING')"),
    )
    op.create_index(
        "uq_refund_attempts_provider_reference",
        "refund_attempts",
        ["provider_code", "provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )
    op.create_index(
        "ix_refund_attempts_history",
        "refund_attempts",
        ["refund_id", "created_at", "id"],
    )
    op.create_table(
        "refund_provider_events",
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
        sa.Column("event_type", sa.String(80), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("reported_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reported_currency", sa.String(3), nullable=False),
        sa.Column("provider_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'RECEIVED'"),
        ),
        sa.Column(
            "refund_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refund_attempts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_refund_provider_events_provider",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[a-f0-9]{64}$'", name="ck_refund_provider_events_hash"
        ),
        sa.CheckConstraint(
            "result IN ('SUCCEEDED','FAILED')", name="ck_refund_provider_events_result"
        ),
        sa.CheckConstraint(
            "processing_status IN ('RECEIVED','PROCESSED','IGNORED','REJECTED')",
            name="ck_refund_provider_events_status",
        ),
        sa.CheckConstraint(
            "(processing_status = 'RECEIVED') = (processed_at IS NULL)",
            name="ck_refund_provider_events_completion",
        ),
        sa.CheckConstraint(
            "reported_amount >= 0 AND reported_amount <> 'NaN'::numeric",
            name="ck_refund_provider_events_amount",
        ),
        sa.CheckConstraint(
            "reported_currency ~ '^[A-Z]{3}$'",
            name="ck_refund_provider_events_currency",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_refund_provider_events_reason",
        ),
        sa.UniqueConstraint(
            "provider_code", "provider_event_id", name="uq_refund_provider_events_key"
        ),
    )
    op.create_table(
        "refund_status_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "refund_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refunds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "refund_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refund_attempts.id", ondelete="RESTRICT"),
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
            "to_status IN ('PENDING','PROCESSING','REFUNDED','FAILED') AND "
            "(from_status IS NULL OR from_status IN "
            "('PENDING','PROCESSING','REFUNDED','FAILED'))",
            name="ck_refund_status_history_status",
        ),
        sa.CheckConstraint(
            "source IN ('STAFF','PROVIDER','SYSTEM')",
            name="ck_refund_status_history_source",
        ),
        sa.CheckConstraint(
            "(source = 'STAFF') = (changed_by_user_id IS NOT NULL)",
            name="ck_refund_status_history_actor",
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status <> to_status",
            name="ck_refund_status_history_transition",
        ),
        sa.CheckConstraint(
            "from_status IS NOT NULL OR (to_status = 'PENDING' AND source = 'SYSTEM')",
            name="ck_refund_status_history_initial",
        ),
    )
    op.create_index(
        "ix_refund_status_history_timeline",
        "refund_status_history",
        ["refund_id", "created_at", "id"],
    )
    op.execute(
        "CREATE TRIGGER trg_cancellation_requests_set_updated_at BEFORE UPDATE ON "
        "cancellation_requests FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER trg_refunds_set_updated_at BEFORE UPDATE ON refunds FOR EACH "
        "ROW EXECUTE FUNCTION restaurant_phase1_set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER trg_refund_attempts_set_updated_at BEFORE UPDATE ON "
        "refund_attempts FOR EACH ROW EXECUTE FUNCTION "
        "restaurant_phase1_set_updated_at()"
    )
    op.execute("""
        INSERT INTO permissions(code,name,description) VALUES
        ('CANCELLATION_VIEW','View branch cancellations',
         'Read cancellation requests and decisions'),
        ('CANCELLATION_MANAGE','Manage branch cancellations',
         'Review requests and cancel orders'),
        ('REFUND_MANAGE','Manage branch refunds','Read and process full refunds')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions(role_id,permission_id)
        SELECT r.id,p.id FROM roles r JOIN permissions p
        ON p.code IN ('CANCELLATION_VIEW','CANCELLATION_MANAGE','REFUND_MANAGE')
        WHERE r.code='ADMIN' AND r.scope='BRANCH'
        ON CONFLICT (role_id,permission_id) DO NOTHING
    """)
    _historical_invariants()


def _historical_invariants():
    # Evaluate the final local state, not a legitimate intermediate write.
    op.execute("""
        CREATE FUNCTION restaurant_phase8_validate_refund() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE target uuid; current_order record; paid_payment record;
        BEGIN
            IF TG_TABLE_NAME = 'orders' THEN
                target := NEW.id;
            ELSIF TG_OP = 'DELETE' THEN
                target := OLD.order_id;
            ELSE
                target := NEW.order_id;
            END IF;
            SELECT id,status,payment_status,total,payment_method_type
              INTO current_order FROM orders WHERE id=target;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT id,amount,currency_code,method_type INTO paid_payment
              FROM payments WHERE order_id=target AND status='PAID';
            IF current_order.status = 'CANCELLED' THEN
                IF EXISTS (SELECT 1 FROM delivery_assignments
                    WHERE order_id=target AND unassigned_at IS NULL
                    AND completed_at IS NULL) THEN
                    RAISE EXCEPTION 'Cancelled order has active fulfillment';
                END IF;
                IF current_order.payment_status='PAID'
                    OR paid_payment.id IS NOT NULL THEN
                    IF paid_payment.id IS NULL
                        OR current_order.payment_status <> 'PAID'
                        OR NOT EXISTS (SELECT 1 FROM refunds
                            WHERE order_id=target
                            AND payment_id=paid_payment.id
                            AND amount=paid_payment.amount
                            AND amount=current_order.total
                            AND currency_code=paid_payment.currency_code
                            AND method_type=paid_payment.method_type
                            AND method_type=current_order.payment_method_type)
                    THEN
                        RAISE EXCEPTION 'Cancelled paid order requires full refund';
                    END IF;
                END IF;
            END IF;
            IF EXISTS (SELECT 1 FROM refunds WHERE order_id=target)
                AND (current_order.status <> 'CANCELLED'
                    OR current_order.payment_status <> 'PAID'
                    OR paid_payment.id IS NULL
                    OR NOT EXISTS (SELECT 1 FROM refunds
                        WHERE order_id=target AND payment_id=paid_payment.id
                        AND amount=paid_payment.amount
                        AND amount=current_order.total
                        AND currency_code=paid_payment.currency_code
                        AND method_type=paid_payment.method_type
                        AND method_type=current_order.payment_method_type))
            THEN
                RAISE EXCEPTION 'Refund must match the original full payment';
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in ("orders", "payments", "refunds", "delivery_assignments"):
        # Only refunds has a DELETE event: paid obligations cannot be removed.
        event = (
            "INSERT OR UPDATE OR DELETE" if table == "refunds" else "INSERT OR UPDATE"
        )
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_phase8_{table}_refund "
            f"AFTER {event} ON {table} DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION restaurant_phase8_validate_refund()"
        )
    op.execute("""
        CREATE FUNCTION restaurant_phase8_protect_history() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF TG_TABLE_NAME = 'refunds' THEN
                IF ROW(NEW.payment_id,NEW.order_id,NEW.amount,NEW.currency_code,
                    NEW.method_type,NEW.reason_code,NEW.requested_at,NEW.created_at)
                    IS DISTINCT FROM ROW(OLD.payment_id,OLD.order_id,OLD.amount,
                    OLD.currency_code,OLD.method_type,OLD.reason_code,
                    OLD.requested_at,OLD.created_at) THEN
                    RAISE EXCEPTION 'Original refund obligation is immutable';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Historical cancellation/refund records are append-only';
        END $$
    """)
    for table in ("order_cancellations", "refund_status_history"):
        op.execute(
            f"CREATE TRIGGER trg_phase8_{table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION restaurant_phase8_protect_history()"
        )
    op.execute(
        "CREATE TRIGGER trg_phase8_refund_snapshot BEFORE UPDATE ON refunds "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase8_protect_history()"
    )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM cancellation_requests) OR
               EXISTS (SELECT 1 FROM order_cancellations) OR
               EXISTS (SELECT 1 FROM refunds) OR
               EXISTS (SELECT 1 FROM refund_attempts) OR
               EXISTS (SELECT 1 FROM refund_provider_events) OR
               EXISTS (SELECT 1 FROM refund_status_history) THEN
                RAISE EXCEPTION 'Cancellation/refund history is nonempty; preserve it';
            END IF;
        END $$
    """)
    for table in ("orders", "payments", "refunds", "delivery_assignments"):
        op.execute(f"DROP TRIGGER trg_phase8_{table}_refund ON {table}")
    for table in ("order_cancellations", "refund_status_history"):
        op.execute(f"DROP TRIGGER trg_phase8_{table}_immutable ON {table}")
    op.execute("DROP TRIGGER trg_phase8_refund_snapshot ON refunds")
    op.execute("DROP FUNCTION restaurant_phase8_validate_refund()")
    op.execute("DROP FUNCTION restaurant_phase8_protect_history()")
    op.execute(
        "DROP TRIGGER trg_cancellation_requests_set_updated_at ON cancellation_requests"
    )
    op.execute("DROP TRIGGER trg_refunds_set_updated_at ON refunds")
    op.execute("DROP TRIGGER trg_refund_attempts_set_updated_at ON refund_attempts")
    op.drop_table("refund_status_history")
    op.drop_table("refund_provider_events")
    op.drop_table("refund_attempts")
    op.drop_table("refunds")
    op.drop_table("order_cancellations")
    op.drop_table("cancellation_requests")
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions WHERE code IN
        ('CANCELLATION_VIEW','CANCELLATION_MANAGE','REFUND_MANAGE'))
    """)
    op.execute("""
        DELETE FROM permissions WHERE code IN
        ('CANCELLATION_VIEW','CANCELLATION_MANAGE','REFUND_MANAGE')
    """)
