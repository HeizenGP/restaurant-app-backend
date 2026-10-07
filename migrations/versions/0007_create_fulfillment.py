"""Fulfillment histories, pickup release index and branch permissions.
Revision ID: 0007_fulfillment
Revises: 0006_payments
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_fulfillment"
down_revision = "0006_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_assignments",
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
            "assigned_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "unassigned_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "NOT (unassigned_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_delivery_assignments_terminal",
        ),
        sa.CheckConstraint(
            "(unassigned_at IS NULL) = (unassigned_by_user_id IS NULL)",
            name="ck_delivery_assignments_actor",
        ),
        sa.CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at",
            name="ck_delivery_assignments_unassigned_time",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= assigned_at",
            name="ck_delivery_assignments_completed_time",
        ),
    )
    op.create_index(
        "uq_delivery_assignments_active",
        "delivery_assignments",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL AND completed_at IS NULL"),
    )
    op.create_index(
        "ix_delivery_assignments_history",
        "delivery_assignments",
        ["order_id", "assigned_at", "id"],
    )
    op.create_index(
        "ix_delivery_assignments_staff",
        "delivery_assignments",
        ["assigned_user_id", "assigned_at", "id"],
    )
    op.create_table(
        "delivery_delay_incidents",
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
        sa.Column("committed_eta", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "delay_threshold_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("900"),
        ),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_order_status", sa.String(24), nullable=False),
        sa.Column("delay_seconds_at_detection", sa.Integer(), nullable=False),
        sa.Column(
            "decision_status",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'OPEN'"),
        ),
        sa.Column(
            "evaluated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_responsibility", sa.Boolean(), nullable=True),
        sa.Column("evaluation_note", sa.Text(), nullable=True),
        sa.Column("remediation_description", sa.Text(), nullable=True),
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
            "delay_threshold_seconds = 900 AND delay_seconds_at_detection > "
            "delay_threshold_seconds",
            name="ck_delivery_delay_incidents_threshold",
        ),
        sa.CheckConstraint(
            "observed_order_status IN "
            "('WAITING','PREPARING','READY','OUT_FOR_DELIVERY','DELIVERED')",
            name="ck_delivery_delay_incidents_observed",
        ),
        sa.CheckConstraint(
            "decision_status IN ('OPEN','APPROVED','REJECTED')",
            name="ck_delivery_delay_incidents_status",
        ),
        sa.CheckConstraint(
            "(decision_status = 'OPEN' AND evaluated_at IS NULL AND "
            "evaluated_by_user_id IS NULL AND customer_responsibility IS NULL "
            "AND evaluation_note IS NULL AND remediation_description IS NULL) "
            "OR (decision_status IN ('APPROVED','REJECTED') AND evaluated_at "
            "IS NOT NULL AND evaluated_by_user_id IS NOT NULL AND evaluated_at "
            ">= detected_at)",
            name="ck_delivery_delay_incidents_evaluation",
        ),
        sa.CheckConstraint(
            "(decision_status = 'APPROVED' AND remediation_description IS NOT "
            "NULL AND length(btrim(remediation_description)) BETWEEN 1 AND "
            "2000) OR (decision_status <> 'APPROVED' AND "
            "remediation_description IS NULL)",
            name="ck_delivery_delay_incidents_remediation",
        ),
        sa.CheckConstraint(
            "evaluation_note IS NULL OR length(btrim(evaluation_note)) BETWEEN "
            "1 AND 2000",
            name="ck_delivery_delay_incidents_note",
        ),
        sa.UniqueConstraint("order_id", name="uq_delivery_delay_incidents_order"),
    )
    op.create_index(
        "ix_delivery_delay_incidents_review",
        "delivery_delay_incidents",
        ["branch_id", "decision_status", "detected_at", "id"],
    )
    op.create_index(
        "ix_delivery_delay_incidents_recent",
        "delivery_delay_incidents",
        ["branch_id", "detected_at", "id"],
    )
    op.create_index(
        "ix_orders_pickup_release",
        "orders",
        ["branch_id", "order_number", "id"],
        postgresql_where=sa.text(
            "mode = 'PICKUP' AND status = 'SCHEDULED' AND payment_status = 'PAID'"
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_delivery_delay_incidents_set_updated_at "
        "BEFORE UPDATE ON delivery_delay_incidents FOR EACH ROW "
        "EXECUTE FUNCTION restaurant_phase1_set_updated_at()"
    )
    op.execute("""
        INSERT INTO permissions(code,name,description) VALUES
        ('FULFILLMENT_VIEW','View branch fulfillment',
         'Read pickup and delivery operations'),
        ('FULFILLMENT_MANAGE','Manage branch fulfillment',
         'Release and hand over paid orders'),
        ('DELIVERY_ASSIGN','Assign branch delivery','Assign active branch staff'),
        ('DELIVERY_DELAY_REVIEW','Review delivery delays',
         'Detect and evaluate delivery incidents')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions(role_id,permission_id)
        SELECT r.id,p.id FROM roles r JOIN permissions p
        ON p.code IN ('FULFILLMENT_VIEW','FULFILLMENT_MANAGE',
                     'DELIVERY_ASSIGN','DELIVERY_DELAY_REVIEW')
        WHERE r.code='ADMIN' AND r.scope='BRANCH'
        ON CONFLICT (role_id,permission_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM delivery_assignments) OR
               EXISTS (SELECT 1 FROM delivery_delay_incidents) THEN
                RAISE EXCEPTION 'Fulfillment history is nonempty; preserve it';
            END IF;
        END $$
    """)
    op.drop_index("ix_orders_pickup_release", table_name="orders")
    op.execute(
        "DROP TRIGGER trg_delivery_delay_incidents_set_updated_at "
        "ON delivery_delay_incidents"
    )
    op.drop_table("delivery_delay_incidents")
    op.drop_table("delivery_assignments")
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions WHERE code IN
        ('FULFILLMENT_VIEW','FULFILLMENT_MANAGE','DELIVERY_ASSIGN','DELIVERY_DELAY_REVIEW'))
    """)
    op.execute("""
        DELETE FROM permissions WHERE code IN
        ('FULFILLMENT_VIEW','FULFILLMENT_MANAGE','DELIVERY_ASSIGN','DELIVERY_DELAY_REVIEW')
    """)
