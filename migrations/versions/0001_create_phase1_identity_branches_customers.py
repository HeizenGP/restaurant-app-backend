"""Create Phase 1 identity, customer and branch persistence.

Revision ID: 0001_phase1
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase1"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions are shared database capabilities. The downgrade deliberately
    # leaves them installed because another schema may also depend on them.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "roles",
        sa.Column(
            "id",
            sa.SmallInteger(),
            sa.Identity(start=1),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope IN ('GLOBAL', 'BRANCH')",
            name="ck_roles_scope",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
    )
    op.create_table(
        "permissions",
        sa.Column(
            "id",
            sa.SmallInteger(),
            sa.Identity(start=1),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column(
            "account_status",
            sa.String(length=20),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "account_status IN ('ACTIVE', 'BLOCKED', 'DISABLED')",
            name="ck_users_account_status",
        ),
        sa.CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL",
            name="ck_users_contact_required",
        ),
        sa.CheckConstraint(
            "phone IS NULL OR phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_users_phone_format",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
    )
    op.create_index(
        "ix_users_active_status",
        "users",
        ["account_status"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "branches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address_line", sa.Text(), nullable=False),
        sa.Column("district", sa.String(length=120), nullable=False),
        sa.Column(
            "city",
            sa.String(length=120),
            server_default=sa.text("'Tarapoto'"),
            nullable=False,
        ),
        sa.Column(
            "department",
            sa.String(length=120),
            server_default=sa.text("'San Martín'"),
            nullable=False,
        ),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'America/Lima'"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_branches_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_branches_longitude",
        ),
        sa.CheckConstraint(
            "phone IS NULL OR phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_branches_phone_format",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_branches"),
        sa.UniqueConstraint("code", name="uq_branches_code"),
    )
    op.create_index(
        "ix_branches_active",
        "branches",
        ["is_active"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "customers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("full_name", sa.String(length=180), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_guest",
            sa.Boolean(),
            sa.Computed("(user_id IS NULL)", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_customers_phone_format",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_customers_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("phone", name="uq_customers_phone"),
        sa.UniqueConstraint("user_id", name="uq_customers_user_id"),
    )
    op.create_index(
        "ix_customers_email",
        "customers",
        ["email"],
        unique=False,
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("permission_id", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_role_permissions_role_id_roles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "role_id",
            "permission_id",
            name="pk_role_permissions",
        ),
    )
    op.create_index(
        "ix_role_permissions_permission_id",
        "role_permissions",
        ["permission_id"],
        unique=False,
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_user_roles_role_id_roles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_roles_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )
    op.create_index(
        "ix_user_roles_role_id",
        "user_roles",
        ["role_id"],
        unique=False,
    )
    op.create_table(
        "refresh_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_refresh_tokens_expiry",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_refresh_tokens_revocation_time",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_refresh_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_refresh_tokens_token_hash",
        ),
    )
    op.create_index(
        "ix_refresh_tokens_user_state",
        "refresh_tokens",
        ["user_id", "expires_at", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "branch_hours",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column(
            "is_closed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "day_of_week BETWEEN 0 AND 6",
            name="ck_branch_hours_day_of_week",
        ),
        sa.CheckConstraint(
            "(is_closed IS TRUE AND open_time IS NULL AND close_time IS NULL) "
            "OR (is_closed IS FALSE AND open_time IS NOT NULL "
            "AND close_time IS NOT NULL)",
            name="ck_branch_hours_schedule",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_branch_hours_branch_id_branches",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_branch_hours"),
        sa.UniqueConstraint(
            "branch_id",
            "day_of_week",
            name="uq_branch_hours_branch_day",
        ),
    )
    op.create_table(
        "staff_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("employee_code", sa.String(length=40), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= assigned_at",
            name="ck_staff_assignments_dates",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["branches.id"],
            name="fk_staff_assignments_branch_id_branches",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_staff_assignments_role_id_roles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_staff_assignments_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_staff_assignments"),
        sa.UniqueConstraint(
            "branch_id",
            "employee_code",
            name="uq_staff_assignments_branch_employee_code",
        ),
        sa.UniqueConstraint(
            "user_id",
            "branch_id",
            "role_id",
            name="uq_staff_assignments_user_branch_role",
        ),
    )
    op.create_index(
        "ix_staff_assignments_branch_active",
        "staff_assignments",
        ["branch_id"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_staff_assignments_user_active",
        "staff_assignments",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_table(
        "otp_challenges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_otp_challenges_attempts_nonnegative",
        ),
        sa.CheckConstraint(
            "attempts <= max_attempts",
            name="ck_otp_challenges_attempts_within_limit",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_otp_challenges_consumption_time",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_otp_challenges_expiry",
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name="ck_otp_challenges_max_attempts_positive",
        ),
        sa.CheckConstraint(
            "phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_otp_challenges_phone_format",
        ),
        sa.CheckConstraint(
            "purpose IN ('GUEST_ACCESS', 'REGISTER', 'LOGIN', 'PHONE_VERIFY')",
            name="ck_otp_challenges_purpose",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_otp_challenges_customer_id_customers",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_otp_challenges"),
    )
    op.create_index(
        "ix_otp_challenges_customer_id",
        "otp_challenges",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_otp_challenges_phone_purpose_created_at",
        "otp_challenges",
        ["phone", "purpose", "created_at"],
        unique=False,
    )
    op.create_table(
        "customer_addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("recipient_name", sa.String(length=180), nullable=False),
        sa.Column("recipient_phone", sa.String(length=20), nullable=False),
        sa.Column("address_line", sa.Text(), nullable=False),
        sa.Column("reference_text", sa.Text(), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=False),
        sa.Column(
            "city",
            sa.String(length=120),
            server_default=sa.text("'Tarapoto'"),
            nullable=False,
        ),
        sa.Column(
            "department",
            sa.String(length=120),
            server_default=sa.text("'San Martín'"),
            nullable=False,
        ),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=10, scale=7), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_customer_addresses_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_customer_addresses_longitude",
        ),
        sa.CheckConstraint(
            "recipient_phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_customer_addresses_phone_format",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="fk_customer_addresses_customer_id_customers",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_customer_addresses"),
    )
    op.create_index(
        "ix_customer_addresses_customer_id",
        "customer_addresses",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "uq_customer_addresses_one_default",
        "customer_addresses",
        ["customer_id"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )

    op.execute(
        """
        CREATE FUNCTION restaurant_phase1_set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in ("users", "branches", "customers", "customer_addresses"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_set_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION restaurant_phase1_set_updated_at()
            """
        )

    op.execute(
        """
        CREATE FUNCTION restaurant_assert_user_role_global()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            assigned_scope varchar(20);
        BEGIN
            SELECT scope
              INTO assigned_scope
              FROM roles
             WHERE id = NEW.role_id
             FOR SHARE;

            IF assigned_scope IS DISTINCT FROM 'GLOBAL' THEN
                RAISE EXCEPTION 'user_roles requires a GLOBAL role'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_user_roles_role_scope_global';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_user_roles_enforce_scope
        BEFORE INSERT OR UPDATE OF role_id ON user_roles
        FOR EACH ROW
        EXECUTE FUNCTION restaurant_assert_user_role_global()
        """
    )
    op.execute(
        """
        CREATE FUNCTION restaurant_assert_staff_role_branch()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            assigned_scope varchar(20);
        BEGIN
            SELECT scope
              INTO assigned_scope
              FROM roles
             WHERE id = NEW.role_id
             FOR SHARE;

            IF assigned_scope IS DISTINCT FROM 'BRANCH' THEN
                RAISE EXCEPTION 'staff_assignments requires a BRANCH role'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_staff_assignments_role_scope_branch';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_staff_assignments_enforce_scope
        BEFORE INSERT OR UPDATE OF role_id ON staff_assignments
        FOR EACH ROW
        EXECUTE FUNCTION restaurant_assert_staff_role_branch()
        """
    )
    op.execute(
        """
        CREATE FUNCTION restaurant_protect_role_scope_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.scope IS DISTINCT FROM OLD.scope THEN
                IF NEW.scope = 'GLOBAL'
                   AND EXISTS (
                       SELECT 1
                         FROM staff_assignments
                        WHERE role_id = OLD.id
                   )
                THEN
                    RAISE EXCEPTION
                        'role scope cannot become GLOBAL while assigned to staff'
                        USING ERRCODE = '23514',
                              CONSTRAINT =
                                  'ck_roles_scope_change_preserves_assignments';
                ELSIF NEW.scope = 'BRANCH'
                      AND EXISTS (
                          SELECT 1
                            FROM user_roles
                           WHERE role_id = OLD.id
                      )
                THEN
                    RAISE EXCEPTION
                        'role scope cannot become BRANCH while assigned globally'
                        USING ERRCODE = '23514',
                              CONSTRAINT =
                                  'ck_roles_scope_change_preserves_assignments';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_roles_protect_scope_change
        BEFORE UPDATE OF scope ON roles
        FOR EACH ROW
        EXECUTE FUNCTION restaurant_protect_role_scope_change()
        """
    )

    op.execute(
        """
        INSERT INTO roles (code, name, scope, description)
        VALUES
            ('CUSTOMER', 'Customer', 'GLOBAL',
             'Registered restaurant customer'),
            ('ADMIN', 'Branch administrator', 'BRANCH',
             'Administrator scoped to one restaurant branch'),
            ('KITCHEN', 'Kitchen staff', 'BRANCH',
             'Kitchen staff scoped to one restaurant branch')
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            scope = EXCLUDED.scope,
            description = EXCLUDED.description
        """
    )
    op.execute(
        """
        INSERT INTO permissions (code, name, description)
        VALUES (
            'STAFF_MANAGE',
            'Manage branch staff',
            'Create and maintain staff assignments in an authorized branch'
        )
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            description = EXCLUDED.description
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT role.id, permission.id
          FROM roles AS role
          JOIN permissions AS permission
            ON permission.code = 'STAFF_MANAGE'
         WHERE role.code = 'ADMIN'
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_roles_protect_scope_change ON roles")
    op.execute("DROP FUNCTION IF EXISTS restaurant_protect_role_scope_change()")
    op.execute(
        "DROP TRIGGER IF EXISTS "
        "trg_staff_assignments_enforce_scope ON staff_assignments"
    )
    op.execute("DROP FUNCTION IF EXISTS restaurant_assert_staff_role_branch()")
    op.execute("DROP TRIGGER IF EXISTS trg_user_roles_enforce_scope ON user_roles")
    op.execute("DROP FUNCTION IF EXISTS restaurant_assert_user_role_global()")
    for table_name in reversed(
        ("users", "branches", "customers", "customer_addresses")
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_set_updated_at ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS restaurant_phase1_set_updated_at()")

    op.drop_index(
        "uq_customer_addresses_one_default",
        table_name="customer_addresses",
        postgresql_where=sa.text("is_default IS TRUE"),
    )
    op.drop_index(
        "ix_customer_addresses_customer_id",
        table_name="customer_addresses",
    )
    op.drop_table("customer_addresses")
    op.drop_index(
        "ix_otp_challenges_phone_purpose_created_at",
        table_name="otp_challenges",
    )
    op.drop_index(
        "ix_otp_challenges_customer_id",
        table_name="otp_challenges",
    )
    op.drop_table("otp_challenges")
    op.drop_index(
        "ix_staff_assignments_user_active",
        table_name="staff_assignments",
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.drop_index(
        "ix_staff_assignments_branch_active",
        table_name="staff_assignments",
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.drop_table("staff_assignments")
    op.drop_table("branch_hours")
    op.drop_index(
        "ix_refresh_tokens_user_state",
        table_name="refresh_tokens",
    )
    op.drop_table("refresh_tokens")
    op.drop_index("ix_user_roles_role_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index(
        "ix_role_permissions_permission_id",
        table_name="role_permissions",
    )
    op.drop_table("role_permissions")
    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_table("customers")
    op.drop_index(
        "ix_branches_active",
        table_name="branches",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("branches")
    op.drop_index(
        "ix_users_active_status",
        table_name="users",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("users")
    op.drop_table("permissions")
    op.drop_table("roles")

    # citext and pgcrypto intentionally remain installed.
