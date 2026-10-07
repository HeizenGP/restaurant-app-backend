"""Create global catalog, branch overrides and transactional audit.

Revision ID: 0002_catalog
Revises: 0001_phase1
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_catalog"
down_revision = "0001_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "name = btrim(name) AND length(name) > 0", name="ck_categories_name"
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_categories_slug_format"
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_categories_sort_order"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
    )
    op.create_index(
        "ix_categories_public_order",
        "categories",
        ["sort_order", "name"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE AND deleted_at IS NULL"),
    )
    op.create_table(
        "products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "allows_notes", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_products_name"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_products_slug_format"
        ),
        sa.CheckConstraint("base_price >= 0", name="ck_products_base_price"),
        sa.CheckConstraint("sort_order >= 0", name="ck_products_sort_order"),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
    )
    op.create_index(
        "ix_products_category_order",
        "products",
        ["category_id", "sort_order", "name"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "product_images",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("alt_text", sa.String(300), nullable=True),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_primary", sa.Boolean, nullable=False, server_default=sa.text("false")
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "url ~ '^https?://[^[:space:]]+$'", name="ck_product_images_url"
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_product_images_sort_order"),
    )
    op.create_index(
        "ix_product_images_product_order",
        "product_images",
        ["product_id", "sort_order"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_product_images_primary",
        "product_images",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_primary IS TRUE AND deleted_at IS NULL"),
    )
    op.create_table(
        "product_presentations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("price_delta", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "is_default", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name="ck_product_presentations_name"
        ),
        sa.CheckConstraint(
            "price_delta >= 0", name="ck_product_presentations_price_delta"
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_product_presentations_sort_order"
        ),
    )
    op.create_index(
        "ix_product_presentations_public_order",
        "product_presentations",
        ["product_id", "sort_order", "name"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_product_presentations_default",
        "product_presentations",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text(
            "is_default IS TRUE AND is_active IS TRUE AND deleted_at IS NULL"
        ),
    )
    op.create_table(
        "product_addons",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "is_required", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "min_select", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "max_select", sa.Integer, nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_product_addons_name"),
        sa.CheckConstraint(
            "min_select >= 0 AND max_select >= 1 AND min_select <= max_select",
            name="ck_product_addons_selection_limits",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_product_addons_sort_order"),
    )
    op.create_index(
        "ix_product_addons_public_order",
        "product_addons",
        ["product_id", "sort_order", "name"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE AND deleted_at IS NULL"),
    )
    op.create_table(
        "product_addon_options",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "product_addon_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("product_addons.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("additional_price", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "sort_order", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "is_active", sa.Boolean, nullable=False, server_default=sa.text("true")
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
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "length(btrim(name)) > 0", name="ck_product_addon_options_name"
        ),
        sa.CheckConstraint(
            "additional_price >= 0", name="ck_product_addon_options_additional_price"
        ),
        sa.CheckConstraint(
            "sort_order >= 0", name="ck_product_addon_options_sort_order"
        ),
    )
    op.create_index(
        "ix_product_addon_options_public_order",
        "product_addon_options",
        ["product_addon_id", "sort_order", "name"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE AND deleted_at IS NULL"),
    )
    op.create_table(
        "branch_products",
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
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "is_available", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("price_override", sa.Numeric(12, 2), nullable=True),
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
            "price_override IS NULL OR price_override >= 0",
            name="ck_branch_products_price_override",
        ),
        sa.UniqueConstraint(
            "branch_id", "product_id", name="uq_branch_products_branch_id_product_id"
        ),
    )
    op.create_index(
        "ix_branch_products_product", "branch_products", ["product_id"], unique=False
    )
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("before_state", postgresql.JSONB()),
        sa.Column("after_state", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"]
    )
    op.create_index(
        "ix_audit_logs_entity_created",
        "audit_logs",
        ["entity_type", "entity_id", "created_at"],
    )
    for table in (
        "categories",
        "products",
        "product_images",
        "product_presentations",
        "product_addons",
        "product_addon_options",
        "branch_products",
    ):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION restaurant_phase1_set_updated_at()
        """)
    op.execute("""
        INSERT INTO permissions (code, name, description)
        VALUES ('CATALOG_MANAGE', 'Manage restaurant catalog',
                'Manage global catalog and authorized branch product overrides')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT role.id, permission.id FROM roles AS role
        JOIN permissions AS permission ON permission.code = 'CATALOG_MANAGE'
        WHERE role.code = 'ADMIN' AND role.scope = 'BRANCH'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions WHERE code = 'CATALOG_MANAGE')
    """)
    op.execute("DELETE FROM permissions WHERE code = 'CATALOG_MANAGE'")
    for table in (
        "branch_products",
        "product_addon_options",
        "product_addons",
        "product_presentations",
        "product_images",
        "products",
        "categories",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON {table}")
    op.drop_table("audit_logs")
    op.drop_table("branch_products")
    op.drop_table("product_addon_options")
    op.drop_table("product_addons")
    op.drop_table("product_presentations")
    op.drop_table("product_images")
    op.drop_table("products")
    op.drop_table("categories")
