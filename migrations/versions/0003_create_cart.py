"""Create customer carts and backend-generated price snapshots.

Revision ID: 0003_cart
Revises: 0002_catalog
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_cart"
down_revision = "0002_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
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
        sa.Column(
            "status", sa.String(16), nullable=False, server_default=sa.text("'ACTIVE'")
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
        sa.CheckConstraint("status IN ('ACTIVE', 'ABANDONED')", name="ck_carts_status"),
    )
    op.create_index(
        "uq_carts_active_customer",
        "carts",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_carts_branch_status", "carts", ["branch_id", "status"], unique=False
    )
    op.create_table(
        "cart_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "cart_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("carts.id", ondelete="RESTRICT"),
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
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("base_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("presentation_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("addons_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(18, 2), nullable=False),
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
            "quantity BETWEEN 1 AND 10000", name="ck_cart_items_quantity"
        ),
        sa.CheckConstraint(
            "base_price_snapshot >= 0", name="ck_cart_items_base_price_snapshot"
        ),
        sa.CheckConstraint(
            "presentation_price_snapshot >= 0",
            name="ck_cart_items_presentation_price_snapshot",
        ),
        sa.CheckConstraint(
            "addons_price_snapshot >= 0", name="ck_cart_items_addons_price_snapshot"
        ),
        sa.CheckConstraint(
            "unit_price_snapshot >= 0", name="ck_cart_items_unit_price_snapshot"
        ),
        sa.CheckConstraint(
            "unit_price_snapshot = presentation_price_snapshot + addons_price_snapshot",
            name="ck_cart_items_unit_price",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR (length(notes) BETWEEN 1 AND 1000 "
            "AND notes = btrim(notes))",
            name="ck_cart_items_notes",
        ),
    )
    op.create_index(
        "ix_cart_items_cart_order",
        "cart_items",
        ["cart_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "cart_item_addon_options",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "cart_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cart_items.id", ondelete="CASCADE"),
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
        sa.Column("additional_price_snapshot", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "additional_price_snapshot >= 0", name="ck_cart_item_addon_options_price"
        ),
        sa.UniqueConstraint(
            "cart_item_id",
            "product_addon_option_id",
            name="uq_cart_item_addon_options_item_option",
        ),
    )
    for table in ("carts", "cart_items"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION restaurant_phase1_set_updated_at()
        """)


def downgrade() -> None:
    for table in ("cart_items", "carts"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table}")
    op.drop_table("cart_item_addon_options")
    op.drop_table("cart_items")
    op.drop_table("carts")
