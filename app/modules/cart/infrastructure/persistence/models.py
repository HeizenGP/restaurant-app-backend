from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class CartModel(SQLModel, table=True):
    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'ABANDONED')", name="ck_carts_status"),
        Index(
            "uq_carts_active_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_carts_branch_status", "branch_id", "status"),
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
    status: str = Field(
        default="ACTIVE",
        sa_column=Column(String(16), nullable=False, server_default=text("'ACTIVE'")),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )


class CartItemModel(SQLModel, table=True):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 10000", name="ck_cart_items_quantity"),
        CheckConstraint(
            "base_price_snapshot >= 0", name="ck_cart_items_base_price_snapshot"
        ),
        CheckConstraint(
            "presentation_price_snapshot >= 0",
            name="ck_cart_items_presentation_price_snapshot",
        ),
        CheckConstraint(
            "addons_price_snapshot >= 0", name="ck_cart_items_addons_price_snapshot"
        ),
        CheckConstraint(
            "unit_price_snapshot >= 0", name="ck_cart_items_unit_price_snapshot"
        ),
        CheckConstraint(
            "unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot",
            name="ck_cart_items_unit_price",
        ),
        CheckConstraint(
            "notes IS NULL OR (length(notes) BETWEEN 1 AND 1000 "
            "AND notes = btrim(notes))",
            name="ck_cart_items_notes",
        ),
        Index("ix_cart_items_cart_order", "cart_id", "created_at", "id"),
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
    cart_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("carts.id", ondelete="RESTRICT"),
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
    quantity: int = Field(sa_column=Column(Integer, nullable=False))
    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
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
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )


class CartItemAddonOptionModel(SQLModel, table=True):
    __tablename__ = "cart_item_addon_options"
    __table_args__ = (
        CheckConstraint(
            "additional_price_snapshot >= 0", name="ck_cart_item_addon_options_price"
        ),
        UniqueConstraint(
            "cart_item_id",
            "product_addon_option_id",
            name="uq_cart_item_addon_options_item_option",
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
    cart_item_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("cart_items.id", ondelete="CASCADE"),
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
    additional_price_snapshot: Decimal = Field(
        sa_column=Column(Numeric(18, 2), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
