from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class CategoryModel(SQLModel, table=True):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(
            "name = btrim(name) AND length(name) > 0", name="ck_categories_name"
        ),
        CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_categories_slug_format"
        ),
        CheckConstraint("sort_order >= 0", name="ck_categories_sort_order"),
        UniqueConstraint("slug", name="uq_categories_slug"),
        UniqueConstraint("name", name="uq_categories_name"),
        Index(
            "ix_categories_public_order",
            "sort_order",
            "name",
            unique=False,
            postgresql_where=text("is_active IS TRUE AND deleted_at IS NULL"),
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
    name: str = Field(sa_column=Column(CITEXT(), nullable=False))
    slug: str = Field(sa_column=Column(String(160), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    sort_order: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
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
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ProductModel(SQLModel, table=True):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_products_name"),
        CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_products_slug_format"
        ),
        CheckConstraint("base_price >= 0", name="ck_products_base_price"),
        CheckConstraint("sort_order >= 0", name="ck_products_sort_order"),
        UniqueConstraint("slug", name="uq_products_slug"),
        Index(
            "ix_products_category_order",
            "category_id",
            "sort_order",
            "name",
            unique=False,
            postgresql_where=text("deleted_at IS NULL"),
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
    category_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(CITEXT(), nullable=False))
    slug: str = Field(sa_column=Column(String(160), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    base_price: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    allows_notes: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    sort_order: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
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
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ProductImageModel(SQLModel, table=True):
    __tablename__ = "product_images"
    __table_args__ = (
        CheckConstraint(
            "url ~ '^https?://[^[:space:]]+$'", name="ck_product_images_url"
        ),
        CheckConstraint("sort_order >= 0", name="ck_product_images_sort_order"),
        Index(
            "ix_product_images_product_order",
            "product_id",
            "sort_order",
            unique=False,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_product_images_primary",
            "product_id",
            unique=True,
            postgresql_where=text("is_primary IS TRUE AND deleted_at IS NULL"),
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
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    url: str = Field(sa_column=Column(String(2048), nullable=False))
    alt_text: str | None = Field(
        default=None, sa_column=Column(String(300), nullable=True)
    )
    sort_order: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    is_primary: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
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
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ProductPresentationModel(SQLModel, table=True):
    __tablename__ = "product_presentations"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(name)) > 0", name="ck_product_presentations_name"
        ),
        CheckConstraint(
            "price_delta >= 0", name="ck_product_presentations_price_delta"
        ),
        CheckConstraint("sort_order >= 0", name="ck_product_presentations_sort_order"),
        Index(
            "ix_product_presentations_public_order",
            "product_id",
            "sort_order",
            "name",
            unique=False,
            postgresql_where=text("is_active IS TRUE AND deleted_at IS NULL"),
        ),
        Index(
            "uq_product_presentations_default",
            "product_id",
            unique=True,
            postgresql_where=text(
                "is_default IS TRUE AND is_active IS TRUE AND deleted_at IS NULL"
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
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(CITEXT(), nullable=False))
    price_delta: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    sort_order: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
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
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ProductAddonModel(SQLModel, table=True):
    __tablename__ = "product_addons"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="ck_product_addons_name"),
        CheckConstraint(
            "min_select >= 0 AND max_select >= 1 AND min_select <= max_select",
            name="ck_product_addons_selection_limits",
        ),
        CheckConstraint("sort_order >= 0", name="ck_product_addons_sort_order"),
        Index(
            "ix_product_addons_public_order",
            "product_id",
            "sort_order",
            "name",
            unique=False,
            postgresql_where=text("is_active IS TRUE AND deleted_at IS NULL"),
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
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(CITEXT(), nullable=False))
    is_required: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    min_select: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    max_select: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default=text("1"))
    )
    sort_order: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
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
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class ProductAddonOptionModel(SQLModel, table=True):
    __tablename__ = "product_addon_options"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(name)) > 0", name="ck_product_addon_options_name"
        ),
        CheckConstraint(
            "additional_price >= 0", name="ck_product_addon_options_additional_price"
        ),
        CheckConstraint("sort_order >= 0", name="ck_product_addon_options_sort_order"),
        Index(
            "ix_product_addon_options_public_order",
            "product_addon_id",
            "sort_order",
            "name",
            unique=False,
            postgresql_where=text("is_active IS TRUE AND deleted_at IS NULL"),
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
    product_addon_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("product_addons.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    name: str = Field(sa_column=Column(CITEXT(), nullable=False))
    additional_price: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    sort_order: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default=text("0"))
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
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
    deleted_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class BranchProductModel(SQLModel, table=True):
    __tablename__ = "branch_products"
    __table_args__ = (
        CheckConstraint(
            "price_override IS NULL OR price_override >= 0",
            name="ck_branch_products_price_override",
        ),
        UniqueConstraint(
            "branch_id", "product_id", name="uq_branch_products_branch_id_product_id"
        ),
        Index("ix_branch_products_product", "product_id", unique=False),
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
    product_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    is_available: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    price_override: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(12, 2), nullable=True)
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
