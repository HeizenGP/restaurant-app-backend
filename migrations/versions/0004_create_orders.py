"""Historical orders and branch-scoped fulfillment policies.

Revision ID: 0004_orders
Revises: 0003_cart
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_orders"
down_revision = "0003_cart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_carts_status", "carts", type_="check")
    op.create_check_constraint(
        "ck_carts_status", "carts", "status IN ('ACTIVE', 'ABANDONED', 'CHECKED_OUT')"
    )
    op.create_table(
        "restaurant_tables",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column(
            "qr_token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
            "length(btrim(label)) BETWEEN 1 AND 80", name="ck_restaurant_tables_label"
        ),
        sa.UniqueConstraint("qr_token", name="uq_restaurant_tables_qr"),
    )
    op.create_index(
        "ix_restaurant_tables_branch_active",
        "restaurant_tables",
        ["branch_id", "is_active"],
        unique=False,
    )
    op.create_table(
        "branch_order_settings",
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "cash_payment_requires_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "delivery_minimum_order",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "default_prep_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("20"),
        ),
        sa.Column(
            "queue_delay_per_order_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column(
            "pickup_buffer_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column(
            "delivery_default_travel_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("20"),
        ),
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'America/Lima'"),
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
            "delivery_minimum_order >= 0 AND delivery_minimum_order <> 'NaN'::numeric",
            name="ck_branch_order_settings_delivery_minimum_order",
        ),
        sa.CheckConstraint(
            "default_prep_minutes BETWEEN 1 AND 1440",
            name="ck_branch_order_settings_default_prep_minutes",
        ),
        sa.CheckConstraint(
            "queue_delay_per_order_minutes BETWEEN 0 AND 1440",
            name="ck_branch_order_settings_queue_delay_per_order_minutes",
        ),
        sa.CheckConstraint(
            "pickup_buffer_minutes BETWEEN 0 AND 1440",
            name="ck_branch_order_settings_pickup_buffer_minutes",
        ),
        sa.CheckConstraint(
            "delivery_default_travel_minutes BETWEEN 0 AND 1440",
            name="ck_branch_order_settings_delivery_default_travel_minutes",
        ),
        sa.CheckConstraint(
            "length(btrim(timezone)) BETWEEN 1 AND 64",
            name="ck_branch_order_settings_timezone",
        ),
    )
    op.create_table(
        "delivery_zones",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("district", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "is_free", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("delivery_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("estimated_travel_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
            "delivery_fee >= 0 AND delivery_fee <> 'NaN'::numeric",
            name="ck_delivery_zones_delivery_fee",
        ),
        sa.CheckConstraint(
            "NOT is_free OR delivery_fee = 0", name="ck_delivery_zones_free"
        ),
        sa.CheckConstraint(
            "length(district) BETWEEN 1 AND 120 AND district = btrim(district)",
            name="ck_delivery_zones_district",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 120", name="ck_delivery_zones_name"
        ),
        sa.CheckConstraint(
            "estimated_travel_minutes IS NULL OR estimated_travel_minutes "
            "BETWEEN 0 AND 1440",
            name="ck_delivery_zones_travel",
        ),
    )
    op.create_index(
        "uq_delivery_zones_global_district",
        "delivery_zones",
        ["district"],
        unique=True,
        postgresql_where=sa.text("branch_id IS NULL"),
    )
    op.create_index(
        "uq_delivery_zones_branch_district",
        "delivery_zones",
        ["branch_id", "district"],
        unique=True,
        postgresql_where=sa.text("branch_id IS NOT NULL"),
    )
    op.create_index(
        "ix_delivery_zones_coverage",
        "delivery_zones",
        ["branch_id", "district", "is_active"],
        unique=False,
    )
    op.create_table(
        "orders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "order_number", sa.BigInteger(), sa.Identity(start=1), nullable=False
        ),
        sa.Column(
            "source_cart_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carts.id", ondelete="RESTRICT"),
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
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payment_method_type", sa.String(16), nullable=False),
        sa.Column("payment_status", sa.String(16), nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), nullable=False),
        sa.Column("charges_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("total", sa.Numeric(18, 2), nullable=False),
        sa.Column("customer_name_snapshot", sa.String(180), nullable=False),
        sa.Column("customer_phone_snapshot", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("branch_settings_snapshot", postgresql.JSONB(), nullable=False),
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
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "mode IN ('LOCAL','PICKUP','DELIVERY')", name="ck_orders_mode"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION',"
            "'SCHEDULED','WAITING','PREPARING','READY','READY_FOR_PICKUP',"
            "'OUT_FOR_DELIVERY','SERVED','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_orders_status",
        ),
        sa.CheckConstraint(
            "payment_method_type IN ('ONLINE','CASH')", name="ck_orders_payment_method"
        ),
        sa.CheckConstraint(
            "payment_status IN ('PENDING','PAID')", name="ck_orders_payment_status"
        ),
        sa.CheckConstraint(
            "payment_method_type <> 'ONLINE' OR payment_status = 'PAID' "
            "OR status IN ('PENDING_PAYMENT','CANCELLED')",
            name="ck_orders_payment_gate",
        ),
        sa.CheckConstraint(
            "mode = 'LOCAL' OR payment_method_type = 'ONLINE'",
            name="ck_orders_online_required",
        ),
        sa.CheckConstraint(
            "total = subtotal + charges_total - discount_total AND "
            "delivery_fee <= charges_total",
            name="ck_orders_totals",
        ),
        sa.CheckConstraint(
            "mode = 'DELIVERY' OR delivery_fee = 0", name="ck_orders_delivery_mode_fee"
        ),
        sa.CheckConstraint("order_number > 0", name="ck_orders_number"),
        sa.CheckConstraint(
            "delivery_fee >= 0 AND delivery_fee <> 'NaN'::numeric",
            name="ck_orders_delivery_fee",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name="ck_orders_idempotency_key",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[a-f0-9]{64}$'", name="ck_orders_fingerprint"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(branch_settings_snapshot) = 'object'",
            name="ck_orders_settings_snapshot",
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND subtotal <> 'NaN'::numeric", name="ck_orders_subtotal"
        ),
        sa.CheckConstraint(
            "charges_total >= 0 AND charges_total <> 'NaN'::numeric",
            name="ck_orders_charges_total",
        ),
        sa.CheckConstraint(
            "discount_total >= 0 AND discount_total <> 'NaN'::numeric",
            name="ck_orders_discount_total",
        ),
        sa.CheckConstraint(
            "total >= 0 AND total <> 'NaN'::numeric", name="ck_orders_total"
        ),
        sa.UniqueConstraint("order_number", name="uq_orders_number"),
        sa.UniqueConstraint("source_cart_id", name="uq_orders_source_cart"),
        sa.UniqueConstraint(
            "customer_id", "idempotency_key", name="uq_orders_customer_idempotency"
        ),
    )
    op.create_index(
        "ix_orders_branch_status_created",
        "orders",
        ["branch_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_orders_customer_created",
        "orders",
        ["customer_id", "created_at", "id"],
        unique=False,
    )
    op.create_index("ix_orders_mode_status", "orders", ["mode", "status"], unique=False)
    op.create_table(
        "order_items",
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
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "presentation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_presentations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_name_snapshot", sa.String(150), nullable=False),
        sa.Column("presentation_name_snapshot", sa.String(150), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("base_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("presentation_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("addons_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_total_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "base_price_snapshot >= 0 AND base_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_base_price_snapshot",
        ),
        sa.CheckConstraint(
            "presentation_price_snapshot >= 0 AND presentation_price_snapshot "
            "<> 'NaN'::numeric",
            name="ck_order_items_presentation_price_snapshot",
        ),
        sa.CheckConstraint(
            "addons_price_snapshot >= 0 AND addons_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_addons_price_snapshot",
        ),
        sa.CheckConstraint(
            "unit_price_snapshot >= 0 AND unit_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_unit_price_snapshot",
        ),
        sa.CheckConstraint(
            "line_total_snapshot >= 0 AND line_total_snapshot <> 'NaN'::numeric",
            name="ck_order_items_line_total_snapshot",
        ),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 10000", name="ck_order_items_quantity"
        ),
        sa.CheckConstraint(
            "unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot",
            name="ck_order_items_unit_price",
        ),
        sa.CheckConstraint(
            "line_total_snapshot = unit_price_snapshot * quantity",
            name="ck_order_items_line_total",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR (length(notes) BETWEEN 1 AND 1000 AND notes = "
            "btrim(notes))",
            name="ck_order_items_notes",
        ),
    )
    op.create_index(
        "ix_order_items_order",
        "order_items",
        ["order_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "order_item_addon_options",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_addon_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_addons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_addon_option_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_addon_options.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("addon_name_snapshot", sa.String(180), nullable=False),
        sa.Column("option_name_snapshot", sa.String(180), nullable=False),
        sa.Column("additional_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "additional_price_snapshot >= 0 AND additional_price_snapshot <> "
            "'NaN'::numeric",
            name="ck_order_item_addon_options_additional_price_snapshot",
        ),
        sa.UniqueConstraint(
            "order_item_id",
            "product_addon_option_id",
            name="uq_order_item_addon_options_item_option",
        ),
    )
    op.create_table(
        "order_status_history",
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
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('PENDING_PAYMENT',"
            "'PENDING_CASH_CONFIRMATION','SCHEDULED','WAITING','PREPARING',"
            "'READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY','SERVED',"
            "'PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_order_status_history_from",
        ),
        sa.CheckConstraint(
            "to_status IN ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION',"
            "'SCHEDULED','WAITING','PREPARING','READY','READY_FOR_PICKUP',"
            "'OUT_FOR_DELIVERY','SERVED','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_order_status_history_to",
        ),
    )
    op.create_index(
        "ix_order_status_history_order_created",
        "order_status_history",
        ["order_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "order_local_details",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "restaurant_table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurant_tables.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("table_label_snapshot", sa.String(80), nullable=False),
        sa.Column("payment_choice", sa.String(16), nullable=False),
        sa.Column("cash_confirmation_required_snapshot", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "payment_choice IN ('ONLINE','CASH')", name="ck_order_local_details_payment"
        ),
    )
    op.create_table(
        "order_pickup_details",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("requested_pickup_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "calculated_kitchen_release_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("estimated_ready_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_name_snapshot", sa.String(180), nullable=False),
        sa.Column("pickup_phone_snapshot", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "calculated_kitchen_release_at <= estimated_ready_at AND "
            "estimated_ready_at <= requested_pickup_at",
            name="ck_order_pickup_details_schedule",
        ),
    )
    op.create_table(
        "order_delivery_details",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "customer_address_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customer_addresses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "delivery_zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery_zones.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("delivery_zone_name_snapshot", sa.String(120), nullable=False),
        sa.Column("recipient_name_snapshot", sa.String(180), nullable=False),
        sa.Column("recipient_phone_snapshot", sa.String(20), nullable=False),
        sa.Column("address_line_snapshot", sa.Text(), nullable=False),
        sa.Column("reference_text_snapshot", sa.Text(), nullable=True),
        sa.Column("district_snapshot", sa.String(120), nullable=False),
        sa.Column("city_snapshot", sa.String(120), nullable=False),
        sa.Column("department_snapshot", sa.String(120), nullable=False),
        sa.Column("latitude_snapshot", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude_snapshot", sa.Numeric(10, 7), nullable=True),
        sa.Column("delivery_fee_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("estimated_delivery_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "delivery_fee_snapshot >= 0 AND delivery_fee_snapshot <> 'NaN'::numeric",
            name="ck_order_delivery_details_delivery_fee_snapshot",
        ),
        sa.CheckConstraint(
            "latitude_snapshot IS NULL OR latitude_snapshot BETWEEN -90 AND 90",
            name="ck_order_delivery_details_latitude",
        ),
        sa.CheckConstraint(
            "longitude_snapshot IS NULL OR longitude_snapshot BETWEEN -180 AND 180",
            name="ck_order_delivery_details_longitude",
        ),
    )
    op.create_table(
        "order_schedule_calculations",
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
        sa.Column("queue_depth", sa.Integer(), nullable=False),
        sa.Column("base_prep_minutes", sa.Integer(), nullable=False),
        sa.Column("queue_delay_minutes", sa.Integer(), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), nullable=False),
        sa.Column("travel_minutes", sa.Integer(), nullable=False),
        sa.Column("calculated_release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_ready_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("queue_depth >= 0", name="ck_order_schedule_queue_depth"),
        sa.CheckConstraint(
            "base_prep_minutes >= 0", name="ck_order_schedule_base_prep_minutes"
        ),
        sa.CheckConstraint(
            "queue_delay_minutes >= 0", name="ck_order_schedule_queue_delay_minutes"
        ),
        sa.CheckConstraint(
            "buffer_minutes >= 0", name="ck_order_schedule_buffer_minutes"
        ),
        sa.CheckConstraint(
            "travel_minutes >= 0", name="ck_order_schedule_travel_minutes"
        ),
        sa.UniqueConstraint("order_id", name="uq_order_schedule_order"),
    )
    op.create_index(
        "ix_order_schedule_order_created",
        "order_schedule_calculations",
        ["order_id", "created_at"],
        unique=False,
    )
    for table in (
        "orders",
        "restaurant_tables",
        "branch_order_settings",
        "delivery_zones",
    ):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION restaurant_phase1_set_updated_at()
        """)
    op.execute("""
        INSERT INTO permissions(code, name, description) VALUES
        ('ORDER_MANAGE', 'Manage branch orders', 'Release local cash orders'),
        ('ORDER_SETTINGS_MANAGE', 'Manage branch order settings',
         'Manage settings, tables and delivery zones')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions(role_id, permission_id)
        SELECT role.id, permission.id FROM roles AS role
        JOIN permissions AS permission
        ON permission.code IN ('ORDER_MANAGE', 'ORDER_SETTINGS_MANAGE')
        WHERE role.code = 'ADMIN' AND role.scope = 'BRANCH'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO delivery_zones(name, district, is_free, delivery_fee)
        VALUES ('Tarapoto', 'Tarapoto', TRUE, 0),
               ('Morales', 'Morales', TRUE, 0),
               ('La Banda de Shilcayo', 'La Banda de Shilcayo', TRUE, 0)
        ON CONFLICT (district) WHERE branch_id IS NULL DO NOTHING
    """)


def downgrade() -> None:
    # Refuse rather than mutate historical checked-out carts or destroy Orders
    # before discovering that the old Cart status check cannot be restored.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM carts WHERE status = 'CHECKED_OUT') THEN
                RAISE EXCEPTION '0004 downgrade requires no CHECKED_OUT carts';
            END IF;
        END $$
    """)
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions
         WHERE code IN ('ORDER_MANAGE', 'ORDER_SETTINGS_MANAGE'))
    """)
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('ORDER_MANAGE', 'ORDER_SETTINGS_MANAGE')"
    )
    for table in (
        "orders",
        "restaurant_tables",
        "branch_order_settings",
        "delivery_zones",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table}")
    op.drop_table("order_schedule_calculations")
    op.drop_table("order_delivery_details")
    op.drop_table("order_pickup_details")
    op.drop_table("order_local_details")
    op.drop_table("order_status_history")
    op.drop_table("order_item_addon_options")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("delivery_zones")
    op.drop_table("branch_order_settings")
    op.drop_table("restaurant_tables")
    op.drop_constraint("ck_carts_status", "carts", type_="check")
    op.create_check_constraint(
        "ck_carts_status", "carts", "status IN ('ACTIVE', 'ABANDONED')"
    )
