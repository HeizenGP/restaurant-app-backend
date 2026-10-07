"""Transactional notification capture, push outbox and realtime cursors.
Revision ID: 0009_notifications
Revises: 0008_cancellations_refunds
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_notifications"
down_revision = "0008_cancellations_refunds"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "realtime_order_events",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("order_number", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payment_status", sa.String(8), nullable=False),
        sa.Column("status_changed", sa.Boolean(), nullable=False),
        sa.Column("payment_status_changed", sa.Boolean(), nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "id > 0 AND order_number > 0", name="ck_realtime_order_events_numbers"
        ),
        sa.CheckConstraint(
            "mode IN ('LOCAL','PICKUP','DELIVERY')",
            name="ck_realtime_order_events_mode",
        ),
        sa.CheckConstraint(
            "event_type IN ('ORDER_CREATED','ORDER_CHANGED','DELIVERY_DELAYED')",
            name="ck_realtime_order_events_type",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION','SCHEDULED','WA"
            "ITING','PREPARING','READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY','SERVED"
            "','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_realtime_order_events_status",
        ),
        sa.CheckConstraint(
            "payment_status IN ('PENDING','PAID')",
            name="ck_realtime_order_events_payment",
        ),
        sa.CheckConstraint(
            "event_type <> 'ORDER_CHANGED' OR status_changed OR payment_status_changed",
            name="ck_realtime_order_events_change",
        ),
        sa.CheckConstraint(
            "event_type <> 'DELIVERY_DELAYED' OR (mode = 'DELIVERY' AND source_refere"
            "nce_id IS NOT NULL)",
            name="ck_realtime_order_events_delay",
        ),
    )
    op.create_index(
        "ix_realtime_order_events_branch",
        "realtime_order_events",
        ["branch_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_realtime_order_events_order",
        "realtime_order_events",
        ["order_id", "id"],
        unique=False,
    )
    op.create_table(
        "customer_notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "sequence_id", sa.BigInteger(), sa.Identity(always=True), nullable=False
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
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
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("order_number_snapshot", sa.BigInteger(), nullable=False),
        sa.Column("order_status", sa.String(32), nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "sequence_id > 0 AND order_number_snapshot > 0",
            name="ck_customer_notifications_numbers",
        ),
        sa.CheckConstraint(
            "kind IN ('ORDER_RECEIVED','ORDER_PREPARING','ORDER_READY','ORDER_READY_F"
            "OR_PICKUP','ORDER_OUT_FOR_DELIVERY','ORDER_DELIVERED','DELIVERY_DELAYED'"
            ")",
            name="ck_customer_notifications_kind",
        ),
        sa.CheckConstraint(
            "order_status IS NULL OR order_status IN ('PENDING_PAYMENT','PENDING_CASH"
            "_CONFIRMATION','SCHEDULED','WAITING','PREPARING','READY','READY_FOR_PICK"
            "UP','OUT_FOR_DELIVERY','SERVED','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_customer_notifications_status",
        ),
        sa.CheckConstraint(
            "(kind = 'ORDER_RECEIVED' AND source_kind = 'ORDER' AND source_id = order"
            "_id) OR (kind = 'DELIVERY_DELAYED' AND source_kind = 'DELIVERY_DELAY_INC"
            "IDENT') OR (kind NOT IN ('ORDER_RECEIVED','DELIVERY_DELAYED') AND source"
            "_kind = 'ORDER_STATUS_HISTORY')",
            name="ck_customer_notifications_source",
        ),
        sa.CheckConstraint(
            "read_at IS NULL OR read_at >= created_at",
            name="ck_customer_notifications_read",
        ),
        sa.UniqueConstraint("sequence_id", name="uq_customer_notifications_sequence"),
        sa.UniqueConstraint(
            "source_kind", "source_id", "kind", name="uq_customer_notifications_source"
        ),
    )
    op.create_index(
        "ix_customer_notifications_history",
        "customer_notifications",
        ["customer_id", sa.text("sequence_id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_customer_notifications_unread",
        "customer_notifications",
        ["customer_id", "read_at"],
        unique=False,
    )
    op.create_index(
        "ix_customer_notifications_order",
        "customer_notifications",
        ["order_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "notification_devices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(8), nullable=False),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("push_token", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "generation", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("send_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
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
            "platform IN ('ANDROID','IOS')", name="ck_notification_devices_platform"
        ),
        sa.CheckConstraint(
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_notification_devices_provider",
        ),
        sa.CheckConstraint(
            "octet_length(push_token) BETWEEN 1 AND 2048 AND push_token !~ '[[:space:"
            "][:cntrl:]]'",
            name="ck_notification_devices_token",
        ),
        sa.CheckConstraint(
            "generation >= 1", name="ck_notification_devices_generation"
        ),
        sa.UniqueConstraint(
            "installation_id", name="uq_notification_devices_installation"
        ),
        sa.UniqueConstraint(
            "provider_code", "push_token", name="uq_notification_devices_token"
        ),
    )
    op.create_index(
        "ix_notification_devices_owner",
        "notification_devices",
        ["customer_id", "is_active"],
        unique=False,
    )
    op.create_table(
        "notification_push_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customer_notifications.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_devices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_code", sa.String(32), nullable=False),
        sa.Column("device_generation", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'PENDING'")
        ),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            "provider_code ~ '^[a-z][a-z0-9_-]{0,31}$'",
            name="ck_notification_push_deliveries_provider",
        ),
        sa.CheckConstraint(
            "device_generation >= 1", name="ck_notification_push_deliveries_generation"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SENT','FAILED','CANCELLED')",
            name="ck_notification_push_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 5",
            name="ck_notification_push_deliveries_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'SENT') = (sent_at IS NOT NULL)",
            name="ck_notification_push_deliveries_sent",
        ),
        sa.CheckConstraint(
            "(status = 'PROCESSING') = (locked_until IS NOT NULL) AND (status = 'PROC"
            "ESSING') = (claim_token IS NOT NULL)",
            name="ck_notification_push_deliveries_lease",
        ),
        sa.CheckConstraint(
            "provider_message_id IS NULL OR (status = 'SENT' AND length(provider_mess"
            "age_id) BETWEEN 1 AND 255 AND provider_message_id !~ '[[:cntrl:]]')",
            name="ck_notification_push_deliveries_message",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'",
            name="ck_notification_push_deliveries_failure",
        ),
        sa.UniqueConstraint(
            "notification_id", "device_id", name="uq_notification_push_deliveries_pair"
        ),
    )
    op.create_index(
        "ix_notification_push_deliveries_due",
        "notification_push_deliveries",
        ["status", "next_attempt_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_notification_push_deliveries_reclaim",
        "notification_push_deliveries",
        ["locked_until", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'PROCESSING'"),
    )
    op.create_index(
        "ix_notification_push_deliveries_device",
        "notification_push_deliveries",
        ["device_id", "status"],
        unique=False,
    )
    _capture_functions()


def _capture_functions():
    op.execute("""
        CREATE FUNCTION restaurant_phase9_cursor_gate() RETURNS void
        LANGUAGE sql AS $$ SELECT pg_advisory_xact_lock(907009001::bigint) $$;
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase9_notification(
            p_customer uuid,p_order uuid,p_branch uuid,p_number bigint,
            p_kind varchar,p_status varchar,p_source varchar,p_source_id uuid,
            p_occurred timestamptz) RETURNS void LANGUAGE plpgsql AS $$
        DECLARE inserted uuid;
        BEGIN
            PERFORM restaurant_phase9_cursor_gate();
            INSERT INTO customer_notifications(customer_id,order_id,branch_id,
                order_number_snapshot,kind,order_status,source_kind,source_id,
                created_at)
            VALUES(p_customer,p_order,p_branch,p_number,p_kind,p_status,p_source,
                p_source_id,p_occurred)
            ON CONFLICT ON CONSTRAINT uq_customer_notifications_source DO NOTHING
            RETURNING id INTO inserted;
            IF inserted IS NULL AND NOT EXISTS (
                SELECT 1 FROM customer_notifications
                WHERE source_kind=p_source AND source_id=p_source_id
                AND kind=p_kind AND customer_id=p_customer AND order_id=p_order
                AND branch_id=p_branch AND order_number_snapshot=p_number
                AND order_status IS NOT DISTINCT FROM p_status
                AND created_at=p_occurred) THEN
                RAISE EXCEPTION 'Notification source conflicts with historical fact';
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase9_order_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='UPDATE' AND OLD.status IS NOT DISTINCT FROM NEW.status
                AND OLD.payment_status IS NOT DISTINCT FROM NEW.payment_status
            THEN RETURN NEW; END IF;
            -- Acquire BEFORE identity allocation, keep until transaction ends.
            -- Sequence allocation alone does not guarantee commit ordering.
            PERFORM restaurant_phase9_cursor_gate();
            INSERT INTO realtime_order_events(branch_id,order_id,order_number,mode,
                event_type,status,payment_status,status_changed,
                payment_status_changed,source_reference_id,occurred_at)
            VALUES(NEW.branch_id,NEW.id,NEW.order_number,NEW.mode,
                CASE WHEN TG_OP='INSERT' THEN 'ORDER_CREATED' ELSE 'ORDER_CHANGED' END,
                NEW.status,NEW.payment_status,
                CASE WHEN TG_OP='INSERT' THEN false
                    ELSE OLD.status IS DISTINCT FROM NEW.status END,
                CASE WHEN TG_OP='INSERT' THEN false
                    ELSE OLD.payment_status IS DISTINCT FROM NEW.payment_status END,
                NULL,CASE WHEN TG_OP='INSERT' THEN NEW.created_at
                    ELSE clock_timestamp() END);
            IF TG_OP='INSERT' THEN
                PERFORM restaurant_phase9_notification(NEW.customer_id,NEW.id,
                    NEW.branch_id,NEW.order_number,'ORDER_RECEIVED',NEW.status,
                    'ORDER',NEW.id,NEW.created_at);
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase9_history_notification() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE current_order record; selected_kind varchar;
        BEGIN
            IF NEW.from_status IS NULL OR NEW.from_status=NEW.to_status
                THEN RETURN NEW; END IF;
            SELECT id,branch_id,customer_id,order_number,mode INTO current_order
                FROM orders WHERE id=NEW.order_id;
            IF NOT FOUND THEN RAISE EXCEPTION 'Notification order is missing'; END IF;
            selected_kind:=CASE
                WHEN NEW.to_status='PREPARING' THEN 'ORDER_PREPARING'
                WHEN NEW.to_status='READY'
                    AND current_order.mode IN ('LOCAL','DELIVERY') THEN 'ORDER_READY'
                WHEN NEW.to_status='READY_FOR_PICKUP'
                    AND current_order.mode='PICKUP' THEN 'ORDER_READY_FOR_PICKUP'
                WHEN NEW.to_status='OUT_FOR_DELIVERY'
                    AND current_order.mode='DELIVERY' THEN 'ORDER_OUT_FOR_DELIVERY'
                WHEN NEW.to_status='DELIVERED'
                    AND current_order.mode='DELIVERY' THEN 'ORDER_DELIVERED'
                ELSE NULL END;
            IF selected_kind IS NOT NULL THEN
                PERFORM restaurant_phase9_notification(current_order.customer_id,
                    current_order.id,current_order.branch_id,
                    current_order.order_number,selected_kind,NEW.to_status,
                    'ORDER_STATUS_HISTORY',NEW.id,NEW.created_at);
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase9_delay_notification() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE current_order record;
        BEGIN
            SELECT id,customer_id,branch_id,order_number,mode,status,payment_status
                INTO current_order FROM orders WHERE id=NEW.order_id;
            IF NOT FOUND OR current_order.mode <> 'DELIVERY'
                OR current_order.branch_id <> NEW.branch_id THEN
                RAISE EXCEPTION 'Delay notification source is inconsistent';
            END IF;
            PERFORM restaurant_phase9_cursor_gate();
            INSERT INTO realtime_order_events(branch_id,order_id,order_number,mode,
                event_type,status,payment_status,status_changed,
                payment_status_changed,source_reference_id,occurred_at)
            VALUES(current_order.branch_id,current_order.id,
                current_order.order_number,current_order.mode,'DELIVERY_DELAYED',
                current_order.status,current_order.payment_status,false,false,
                NEW.id,NEW.detected_at);
            PERFORM restaurant_phase9_notification(current_order.customer_id,
                current_order.id,current_order.branch_id,current_order.order_number,
                'DELIVERY_DELAYED',current_order.status,'DELIVERY_DELAY_INCIDENT',
                NEW.id,NEW.detected_at);
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase9_enqueue_push() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO notification_push_deliveries(notification_id,device_id,
                provider_code,device_generation,next_attempt_at)
            SELECT NEW.id,d.id,d.provider_code,d.generation,clock_timestamp()
                FROM notification_devices d
                WHERE d.customer_id=NEW.customer_id AND d.is_active
                FOR SHARE OF d;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE FUNCTION restaurant_phase9_protect_fact() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME='customer_notifications' AND TG_OP='UPDATE' THEN
                IF (to_jsonb(NEW)-'read_at') IS DISTINCT FROM
                    (to_jsonb(OLD)-'read_at')
                    OR (OLD.read_at IS NOT NULL AND
                        OLD.read_at IS DISTINCT FROM NEW.read_at) THEN
                    RAISE EXCEPTION
                        'Notification snapshot and first read are immutable';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Notification/realtime history is append-only';
        END $$;
    """)
    op.execute(
        "CREATE TRIGGER trg_phase9_order_insert AFTER INSERT ON orders "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase9_order_event()"
    )
    op.execute(
        "CREATE TRIGGER trg_phase9_order_update AFTER UPDATE OF status,payment_status "
        "ON orders FOR EACH ROW EXECUTE FUNCTION restaurant_phase9_order_event()"
    )
    op.execute(
        "CREATE TRIGGER trg_phase9_history AFTER INSERT ON order_status_history "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase9_history_notification()"
    )
    op.execute(
        "CREATE TRIGGER trg_phase9_delay AFTER INSERT ON delivery_delay_incidents "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase9_delay_notification()"
    )
    op.execute(
        "CREATE TRIGGER trg_phase9_enqueue AFTER INSERT ON customer_notifications "
        "FOR EACH ROW EXECUTE FUNCTION restaurant_phase9_enqueue_push()"
    )
    for table in ("customer_notifications", "realtime_order_events"):
        op.execute(
            f"CREATE TRIGGER trg_phase9_{table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION restaurant_phase9_protect_fact()"
        )
    for table in ("notification_devices", "notification_push_deliveries"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION restaurant_phase1_set_updated_at()"
        )
    op.execute("""
        INSERT INTO permissions(code,name,description) VALUES
        ('ORDER_REALTIME_VIEW','View branch realtime orders',
         'Read branch-scoped order snapshot, events and SSE')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions(role_id,permission_id)
        SELECT r.id,p.id FROM roles r JOIN permissions p
            ON p.code='ORDER_REALTIME_VIEW'
            WHERE r.code='ADMIN' AND r.scope='BRANCH'
        ON CONFLICT (role_id,permission_id) DO NOTHING
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM realtime_order_events)
                OR EXISTS (SELECT 1 FROM customer_notifications)
                OR EXISTS (SELECT 1 FROM notification_devices)
                OR EXISTS (SELECT 1 FROM notification_push_deliveries) THEN
                RAISE EXCEPTION
                    'Notification/realtime history is nonempty; preserve it';
            END IF;
        END $$;
    """)
    for trigger, table in (
        ("trg_phase9_order_insert", "orders"),
        ("trg_phase9_order_update", "orders"),
        ("trg_phase9_history", "order_status_history"),
        ("trg_phase9_delay", "delivery_delay_incidents"),
        ("trg_phase9_enqueue", "customer_notifications"),
        ("trg_phase9_customer_notifications_immutable", "customer_notifications"),
        ("trg_phase9_realtime_order_events_immutable", "realtime_order_events"),
        ("trg_notification_devices_set_updated_at", "notification_devices"),
        (
            "trg_notification_push_deliveries_set_updated_at",
            "notification_push_deliveries",
        ),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    for signature in (
        "restaurant_phase9_order_event()",
        "restaurant_phase9_history_notification()",
        "restaurant_phase9_delay_notification()",
        "restaurant_phase9_enqueue_push()",
        "restaurant_phase9_protect_fact()",
        "restaurant_phase9_notification(uuid,uuid,uuid,bigint,varchar,varchar,varchar"
        ",uuid,timestamptz)",
        "restaurant_phase9_cursor_gate()",
    ):
        op.execute("DROP FUNCTION " + signature)
    for table in (
        "notification_push_deliveries",
        "notification_devices",
        "customer_notifications",
        "realtime_order_events",
    ):
        op.drop_table(table)
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
            (SELECT id FROM permissions WHERE code='ORDER_REALTIME_VIEW')
    """)
    op.execute("DELETE FROM permissions WHERE code='ORDER_REALTIME_VIEW'")
