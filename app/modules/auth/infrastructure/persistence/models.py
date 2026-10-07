from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RoleModel(SQLModel, table=True):
    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("scope IN ('GLOBAL', 'BRANCH')", name="ck_roles_scope"),
        UniqueConstraint("code", name="uq_roles_code"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(
            SmallInteger,
            Identity(start=1),
            primary_key=True,
            nullable=False,
        ),
    )
    code: str = Field(sa_column=Column(String(40), nullable=False))
    name: str = Field(sa_column=Column(String(80), nullable=False))
    scope: str = Field(sa_column=Column(String(20), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


class PermissionModel(SQLModel, table=True):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("code", name="uq_permissions_code"),)

    id: int | None = Field(
        default=None,
        sa_column=Column(
            SmallInteger,
            Identity(start=1),
            primary_key=True,
            nullable=False,
        ),
    )
    code: str = Field(sa_column=Column(String(80), nullable=False))
    name: str = Field(sa_column=Column(String(120), nullable=False))
    description: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


class RolePermissionModel(SQLModel, table=True):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("ix_role_permissions_permission_id", "permission_id"),)

    role_id: int = Field(
        sa_column=Column(
            SmallInteger,
            ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    permission_id: int = Field(
        sa_column=Column(
            SmallInteger,
            ForeignKey("permissions.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )


class UserModel(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "ix_users_staff_name_prefix",
            text("lower(first_name || ' ' || coalesce(last_name,'')) text_pattern_ops"),
        ),
        Index(
            "ix_users_staff_lastname_prefix", text("lower(last_name) text_pattern_ops")
        ),
        Index(
            "ix_users_staff_email_prefix", text("lower(email::text) text_pattern_ops")
        ),
        Index(
            "ix_users_staff_phone_prefix",
            "phone",
            postgresql_ops={"phone": "varchar_pattern_ops"},
        ),
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL",
            name="ck_users_contact_required",
        ),
        CheckConstraint(
            "phone IS NULL OR phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_users_phone_format",
        ),
        CheckConstraint(
            "account_status IN ('ACTIVE', 'BLOCKED', 'DISABLED')",
            name="ck_users_account_status",
        ),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("phone", name="uq_users_phone"),
        Index(
            "ix_users_active_status",
            "account_status",
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
    email: str | None = Field(default=None, sa_column=Column(CITEXT()))
    phone: str | None = Field(default=None, sa_column=Column(String(20)))
    password_hash: str = Field(sa_column=Column(Text, nullable=False))
    first_name: str = Field(sa_column=Column(String(100), nullable=False))
    last_name: str | None = Field(
        default=None,
        sa_column=Column(String(120)),
    )
    account_status: str = Field(
        default="ACTIVE",
        sa_column=Column(
            String(20),
            nullable=False,
            server_default=text("'ACTIVE'"),
        ),
    )
    phone_verified_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    email_verified_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    last_login_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )


class UserRoleModel(SQLModel, table=True):
    __tablename__ = "user_roles"
    __table_args__ = (Index("ix_user_roles_role_id", "role_id"),)

    user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    role_id: int = Field(
        sa_column=Column(
            SmallInteger,
            ForeignKey("roles.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        )
    )
    assigned_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


class RefreshTokenModel(SQLModel, table=True):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at",
            name="ck_refresh_tokens_expiry",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_refresh_tokens_revocation_time",
        ),
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        Index(
            "ix_refresh_tokens_user_state",
            "user_id",
            "expires_at",
            "revoked_at",
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
    user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    token_hash: str = Field(sa_column=Column(Text, nullable=False))
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
