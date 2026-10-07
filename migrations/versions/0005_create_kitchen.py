"""Kitchen permissions and operational-read indexes; Orders retains ownership.

Revision ID: 0005_kitchen
Revises: 0004_orders
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_kitchen"
down_revision = "0004_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO permissions(code, name, description) VALUES
        ('KITCHEN_VIEW', 'View branch kitchen',
         'Read confirmed operational kitchen orders'),
        ('KITCHEN_MANAGE', 'Manage branch preparation',
         'Start preparation and mark orders ready')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions(role_id, permission_id)
        SELECT role.id, permission.id FROM roles AS role
        JOIN permissions AS permission
        ON permission.code IN ('KITCHEN_VIEW', 'KITCHEN_MANAGE')
        WHERE role.code IN ('ADMIN', 'KITCHEN') AND role.scope = 'BRANCH'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """)
    op.create_index(
        "ix_orders_kitchen_queue",
        "orders",
        ["branch_id", "status", "order_number", "id"],
        unique=False,
        postgresql_where=sa.text(
            "status IN ('WAITING', 'PREPARING', 'READY', 'READY_FOR_PICKUP')"
        ),
    )
    op.create_index(
        "ix_order_status_history_entry",
        "order_status_history",
        ["order_id", "to_status", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_order_status_history_entry", table_name="order_status_history")
    op.drop_index("ix_orders_kitchen_queue", table_name="orders")
    op.execute("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions WHERE code IN ('KITCHEN_VIEW', 'KITCHEN_MANAGE'))
    """)
    op.execute(
        "DELETE FROM permissions WHERE code IN ('KITCHEN_VIEW', 'KITCHEN_MANAGE')"
    )
