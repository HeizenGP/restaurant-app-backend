"""Phase 4 persistence metadata; schema creation belongs only to Alembic."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class RestaurantTableModel(SQLModel, table=True):
    __tablename__ = "restaurant_tables"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(label)) BETWEEN 1 AND 80", name="ck_restaurant_tables_label"
        ),
        UniqueConstraint("qr_token", name="uq_restaurant_tables_qr"),
        Index("ix_restaurant_tables_branch_active", "branch_id", "is_active"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    label: str = Field(sa_column=Column(String(80), nullable=False))
    qr_token: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean(), nullable=False, server_default=text("true")),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class BranchOrderSettingsModel(SQLModel, table=True):
    __tablename__ = "branch_order_settings"
    __table_args__ = (
        CheckConstraint(
            "delivery_minimum_order >= 0 AND delivery_minimum_order <> 'NaN'::numeric",
            name="ck_branch_order_settings_delivery_minimum_order",
        ),
        CheckConstraint(
            "default_prep_minutes BETWEEN 1 AND 1440",
            name="ck_branch_order_settings_default_prep_minutes",
        ),
        CheckConstraint(
            "queue_delay_per_order_minutes BETWEEN 0 AND 1440",
            name="ck_branch_order_settings_queue_delay_per_order_minutes",
        ),
        CheckConstraint(
            "pickup_buffer_minutes BETWEEN 0 AND 1440",
            name="ck_branch_order_settings_pickup_buffer_minutes",
        ),
        CheckConstraint(
            "delivery_default_travel_minutes BETWEEN 0 AND 1440",
            name="ck_branch_order_settings_delivery_default_travel_minutes",
        ),
        CheckConstraint(
            "length(btrim(timezone)) BETWEEN 1 AND 64",
            name="ck_branch_order_settings_timezone",
        ),
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        )
    )
    cash_payment_requires_confirmation: bool = Field(
        default=True,
        sa_column=Column(Boolean(), nullable=False, server_default=text("true")),
    )
    delivery_minimum_order: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(18, 2), nullable=False, server_default=text("0")),
    )
    default_prep_minutes: int = Field(
        default=20,
        sa_column=Column(Integer(), nullable=False, server_default=text("20")),
    )
    queue_delay_per_order_minutes: int = Field(
        default=5, sa_column=Column(Integer(), nullable=False, server_default=text("5"))
    )
    pickup_buffer_minutes: int = Field(
        default=5, sa_column=Column(Integer(), nullable=False, server_default=text("5"))
    )
    delivery_default_travel_minutes: int = Field(
        default=20,
        sa_column=Column(Integer(), nullable=False, server_default=text("20")),
    )
    timezone: str = Field(
        default="America/Lima",
        sa_column=Column(
            String(64), nullable=False, server_default=text("'America/Lima'")
        ),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class DeliveryZoneModel(SQLModel, table=True):
    __tablename__ = "delivery_zones"
    __table_args__ = (
        CheckConstraint(
            "delivery_fee >= 0 AND delivery_fee <> 'NaN'::numeric",
            name="ck_delivery_zones_delivery_fee",
        ),
        CheckConstraint(
            "NOT is_free OR delivery_fee = 0", name="ck_delivery_zones_free"
        ),
        CheckConstraint(
            "length(district) BETWEEN 1 AND 120 AND district = btrim(district)",
            name="ck_delivery_zones_district",
        ),
        CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 120", name="ck_delivery_zones_name"
        ),
        CheckConstraint(
            "estimated_travel_minutes IS NULL OR estimated_travel_minutes "
            "BETWEEN 0 AND 1440",
            name="ck_delivery_zones_travel",
        ),
        Index(
            "uq_delivery_zones_global_district",
            "district",
            unique=True,
            postgresql_where=text("branch_id IS NULL"),
        ),
        Index(
            "uq_delivery_zones_branch_district",
            "branch_id",
            "district",
            unique=True,
            postgresql_where=text("branch_id IS NOT NULL"),
        ),
        Index("ix_delivery_zones_coverage", "branch_id", "district", "is_active"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    branch_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    name: str = Field(sa_column=Column(String(120), nullable=False))
    district: str = Field(sa_column=Column(CITEXT(), nullable=False))
    is_free: bool = Field(
        default=False,
        sa_column=Column(Boolean(), nullable=False, server_default=text("false")),
    )
    delivery_fee: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    estimated_travel_minutes: int | None = Field(
        default=None, sa_column=Column(Integer(), nullable=True)
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean(), nullable=False, server_default=text("true")),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderModel(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("mode IN ('LOCAL','PICKUP','DELIVERY')", name="ck_orders_mode"),
        CheckConstraint(
            "status IN ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION',"
            "'SCHEDULED','WAITING','PREPARING','READY','READY_FOR_PICKUP',"
            "'OUT_FOR_DELIVERY','SERVED','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "payment_method_type IN ('ONLINE','CASH')", name="ck_orders_payment_method"
        ),
        CheckConstraint(
            "payment_status IN ('PENDING','PAID')", name="ck_orders_payment_status"
        ),
        CheckConstraint(
            "payment_method_type <> 'ONLINE' OR payment_status = 'PAID' "
            "OR status IN ('PENDING_PAYMENT','CANCELLED')",
            name="ck_orders_payment_gate",
        ),
        CheckConstraint(
            "mode = 'LOCAL' OR payment_method_type = 'ONLINE'",
            name="ck_orders_online_required",
        ),
        CheckConstraint(
            "total = subtotal + charges_total - discount_total AND "
            "delivery_fee <= charges_total",
            name="ck_orders_totals",
        ),
        CheckConstraint(
            "mode = 'DELIVERY' OR delivery_fee = 0", name="ck_orders_delivery_mode_fee"
        ),
        CheckConstraint("order_number > 0", name="ck_orders_number"),
        CheckConstraint(
            "delivery_fee >= 0 AND delivery_fee <> 'NaN'::numeric",
            name="ck_orders_delivery_fee",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'",
            name="ck_orders_idempotency_key",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[a-f0-9]{64}$'", name="ck_orders_fingerprint"
        ),
        CheckConstraint(
            "jsonb_typeof(branch_settings_snapshot) = 'object'",
            name="ck_orders_settings_snapshot",
        ),
        CheckConstraint(
            "subtotal >= 0 AND subtotal <> 'NaN'::numeric", name="ck_orders_subtotal"
        ),
        CheckConstraint(
            "charges_total >= 0 AND charges_total <> 'NaN'::numeric",
            name="ck_orders_charges_total",
        ),
        CheckConstraint(
            "discount_total >= 0 AND discount_total <> 'NaN'::numeric",
            name="ck_orders_discount_total",
        ),
        CheckConstraint(
            "total >= 0 AND total <> 'NaN'::numeric", name="ck_orders_total"
        ),
        UniqueConstraint("order_number", name="uq_orders_number"),
        UniqueConstraint("source_cart_id", name="uq_orders_source_cart"),
        UniqueConstraint(
            "customer_id", "idempotency_key", name="uq_orders_customer_idempotency"
        ),
        Index("ix_orders_branch_status_created", "branch_id", "status", "created_at"),
        Index("ix_orders_customer_created", "customer_id", "created_at", "id"),
        Index("ix_orders_mode_status", "mode", "status"),
        Index(
            "ix_orders_pickup_release",
            "branch_id",
            "order_number",
            "id",
            postgresql_where=text(
                "mode = 'PICKUP' AND status = 'SCHEDULED' AND payment_status = 'PAID'"
            ),
        ),
        Index(
            "ix_orders_kitchen_queue",
            "branch_id",
            "status",
            "order_number",
            "id",
            postgresql_where=text(
                "status IN ('WAITING', 'PREPARING', 'READY', 'READY_FOR_PICKUP')"
            ),
        ),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    order_number: int | None = Field(
        default=None, sa_column=Column(BigInteger(), Identity(start=1), nullable=False)
    )
    source_cart_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("carts.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    customer_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customers.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    mode: str = Field(sa_column=Column(String(16), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False))
    payment_method_type: str = Field(sa_column=Column(String(16), nullable=False))
    payment_status: str = Field(sa_column=Column(String(16), nullable=False))
    subtotal: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    charges_total: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    discount_total: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    delivery_fee: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    total: Decimal = Field(sa_column=Column(Numeric(18, 2), nullable=False))
    customer_name_snapshot: str = Field(sa_column=Column(String(180), nullable=False))
    customer_phone_snapshot: str = Field(sa_column=Column(String(20), nullable=False))
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    request_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))
    branch_settings_snapshot: dict = Field(sa_column=Column(JSONB(), nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class OrderItemModel(SQLModel, table=True):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint(
            "base_price_snapshot >= 0 AND base_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_base_price_snapshot",
        ),
        CheckConstraint(
            "presentation_price_snapshot >= 0 AND presentation_price_snapshot "
            "<> 'NaN'::numeric",
            name="ck_order_items_presentation_price_snapshot",
        ),
        CheckConstraint(
            "addons_price_snapshot >= 0 AND addons_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_addons_price_snapshot",
        ),
        CheckConstraint(
            "unit_price_snapshot >= 0 AND unit_price_snapshot <> 'NaN'::numeric",
            name="ck_order_items_unit_price_snapshot",
        ),
        CheckConstraint(
            "line_total_snapshot >= 0 AND line_total_snapshot <> 'NaN'::numeric",
            name="ck_order_items_line_total_snapshot",
        ),
        CheckConstraint("quantity BETWEEN 1 AND 10000", name="ck_order_items_quantity"),
        CheckConstraint(
            "unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot",
            name="ck_order_items_unit_price",
        ),
        CheckConstraint(
            "line_total_snapshot = unit_price_snapshot * quantity",
            name="ck_order_items_line_total",
        ),
        CheckConstraint(
            "notes IS NULL OR (length(notes) BETWEEN 1 AND 1000 AND notes = "
            "btrim(notes))",
            name="ck_order_items_notes",
        ),
        Index("ix_order_items_order", "order_id", "created_at", "id"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    presentation_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("product_presentations.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    product_name_snapshot: str = Field(sa_column=Column(String(150), nullable=False))
    presentation_name_snapshot: str = Field(
        sa_column=Column(String(150), nullable=False)
    )
    quantity: int = Field(sa_column=Column(Integer(), nullable=False))
    notes: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    base_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    presentation_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    addons_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    unit_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    line_total_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderAddonOptionModel(SQLModel, table=True):
    __tablename__ = "order_item_addon_options"
    __table_args__ = (
        CheckConstraint(
            "additional_price_snapshot >= 0 AND additional_price_snapshot <> "
            "'NaN'::numeric",
            name="ck_order_item_addon_options_additional_price_snapshot",
        ),
        UniqueConstraint(
            "order_item_id",
            "product_addon_option_id",
            name="uq_order_item_addon_options_item_option",
        ),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    order_item_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("order_items.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    product_addon_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("product_addons.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    product_addon_option_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("product_addon_options.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    addon_name_snapshot: str = Field(sa_column=Column(String(180), nullable=False))
    option_name_snapshot: str = Field(sa_column=Column(String(180), nullable=False))
    additional_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderStatusHistoryModel(SQLModel, table=True):
    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('PENDING_PAYMENT',"
            "'PENDING_CASH_CONFIRMATION','SCHEDULED','WAITING','PREPARING',"
            "'READY','READY_FOR_PICKUP','OUT_FOR_DELIVERY','SERVED',"
            "'PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_order_status_history_from",
        ),
        CheckConstraint(
            "to_status IN ('PENDING_PAYMENT','PENDING_CASH_CONFIRMATION',"
            "'SCHEDULED','WAITING','PREPARING','READY','READY_FOR_PICKUP',"
            "'OUT_FOR_DELIVERY','SERVED','PICKED_UP','DELIVERED','CANCELLED')",
            name="ck_order_status_history_to",
        ),
        Index("ix_order_status_history_order_created", "order_id", "created_at", "id"),
        Index(
            "ix_order_status_history_entry", "order_id", "to_status", "created_at", "id"
        ),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    from_status: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    to_status: str = Field(sa_column=Column(String(32), nullable=False))
    changed_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    reason: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderLocalDetailsModel(SQLModel, table=True):
    __tablename__ = "order_local_details"
    __table_args__ = (
        CheckConstraint(
            "payment_choice IN ('ONLINE','CASH')", name="ck_order_local_details_payment"
        ),
    )
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        )
    )
    restaurant_table_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("restaurant_tables.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    table_label_snapshot: str = Field(sa_column=Column(String(80), nullable=False))
    payment_choice: str = Field(sa_column=Column(String(16), nullable=False))
    cash_confirmation_required_snapshot: bool = Field(
        sa_column=Column(Boolean(), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderPickupDetailsModel(SQLModel, table=True):
    __tablename__ = "order_pickup_details"
    __table_args__ = (
        CheckConstraint(
            "calculated_kitchen_release_at <= estimated_ready_at AND "
            "estimated_ready_at <= requested_pickup_at",
            name="ck_order_pickup_details_schedule",
        ),
    )
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        )
    )
    requested_pickup_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    calculated_kitchen_release_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    estimated_ready_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    pickup_name_snapshot: str = Field(sa_column=Column(String(180), nullable=False))
    pickup_phone_snapshot: str = Field(sa_column=Column(String(20), nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderDeliveryDetailsModel(SQLModel, table=True):
    __tablename__ = "order_delivery_details"
    __table_args__ = (
        CheckConstraint(
            "delivery_fee_snapshot >= 0 AND delivery_fee_snapshot <> 'NaN'::numeric",
            name="ck_order_delivery_details_delivery_fee_snapshot",
        ),
        CheckConstraint(
            "latitude_snapshot IS NULL OR latitude_snapshot BETWEEN -90 AND 90",
            name="ck_order_delivery_details_latitude",
        ),
        CheckConstraint(
            "longitude_snapshot IS NULL OR longitude_snapshot BETWEEN -180 AND 180",
            name="ck_order_delivery_details_longitude",
        ),
    )
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        )
    )
    customer_address_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("customer_addresses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    delivery_zone_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("delivery_zones.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    delivery_zone_name_snapshot: str = Field(
        sa_column=Column(String(120), nullable=False)
    )
    recipient_name_snapshot: str = Field(sa_column=Column(String(180), nullable=False))
    recipient_phone_snapshot: str = Field(sa_column=Column(String(20), nullable=False))
    address_line_snapshot: str = Field(sa_column=Column(Text(), nullable=False))
    reference_text_snapshot: str | None = Field(
        default=None, sa_column=Column(Text(), nullable=True)
    )
    district_snapshot: str = Field(sa_column=Column(String(120), nullable=False))
    city_snapshot: str = Field(sa_column=Column(String(120), nullable=False))
    department_snapshot: str = Field(sa_column=Column(String(120), nullable=False))
    latitude_snapshot: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(9, 6), nullable=True)
    )
    longitude_snapshot: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(10, 7), nullable=True)
    )
    delivery_fee_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    estimated_delivery_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class OrderScheduleCalculationModel(SQLModel, table=True):
    __tablename__ = "order_schedule_calculations"
    __table_args__ = (
        CheckConstraint("queue_depth >= 0", name="ck_order_schedule_queue_depth"),
        CheckConstraint(
            "base_prep_minutes >= 0", name="ck_order_schedule_base_prep_minutes"
        ),
        CheckConstraint(
            "queue_delay_minutes >= 0", name="ck_order_schedule_queue_delay_minutes"
        ),
        CheckConstraint("buffer_minutes >= 0", name="ck_order_schedule_buffer_minutes"),
        CheckConstraint("travel_minutes >= 0", name="ck_order_schedule_travel_minutes"),
        UniqueConstraint("order_id", name="uq_order_schedule_order"),
        Index("ix_order_schedule_order_created", "order_id", "created_at"),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()"),
        ),
    )
    order_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    queue_depth: int = Field(sa_column=Column(Integer(), nullable=False))
    base_prep_minutes: int = Field(sa_column=Column(Integer(), nullable=False))
    queue_delay_minutes: int = Field(sa_column=Column(Integer(), nullable=False))
    buffer_minutes: int = Field(sa_column=Column(Integer(), nullable=False))
    travel_minutes: int = Field(sa_column=Column(Integer(), nullable=False))
    calculated_release_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    estimated_ready_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
