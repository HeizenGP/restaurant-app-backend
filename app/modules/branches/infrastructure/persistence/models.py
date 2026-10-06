from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BranchModel(SQLModel, table=True):
    __tablename__ = "branches"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_branches_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_branches_longitude",
        ),
        CheckConstraint(
            "phone IS NULL OR phone ~ '^[+]?[0-9]{9,15}$'",
            name="ck_branches_phone_format",
        ),
        UniqueConstraint("code", name="uq_branches_code"),
        Index(
            "ix_branches_active",
            "is_active",
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
    code: str = Field(sa_column=Column(String(40), nullable=False))
    name: str = Field(sa_column=Column(String(150), nullable=False))
    address_line: str = Field(sa_column=Column(Text, nullable=False))
    district: str = Field(sa_column=Column(String(120), nullable=False))
    city: str = Field(
        default="Tarapoto",
        sa_column=Column(
            String(120),
            nullable=False,
            server_default=text("'Tarapoto'"),
        ),
    )
    department: str = Field(
        default="San Martín",
        sa_column=Column(
            String(120),
            nullable=False,
            server_default=text("'San Martín'"),
        ),
    )
    latitude: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(9, 6)),
    )
    longitude: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(10, 7)),
    )
    phone: str | None = Field(
        default=None,
        sa_column=Column(String(20)),
    )
    timezone: str = Field(
        default="America/Lima",
        sa_column=Column(
            String(64),
            nullable=False,
            server_default=text("'America/Lima'"),
        ),
    )
    is_active: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("true"),
        ),
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


class BranchHourModel(SQLModel, table=True):
    __tablename__ = "branch_hours"
    __table_args__ = (
        CheckConstraint(
            "day_of_week BETWEEN 0 AND 6",
            name="ck_branch_hours_day_of_week",
        ),
        CheckConstraint(
            "("
            "is_closed IS TRUE AND open_time IS NULL AND close_time IS NULL"
            ") OR ("
            "is_closed IS FALSE AND open_time IS NOT NULL AND close_time IS NOT NULL"
            ")",
            name="ck_branch_hours_schedule",
        ),
        UniqueConstraint(
            "branch_id",
            "day_of_week",
            name="uq_branch_hours_branch_day",
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
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    day_of_week: int = Field(sa_column=Column(SmallInteger, nullable=False))
    open_time: time | None = Field(
        default=None,
        sa_column=Column(Time(timezone=False)),
    )
    close_time: time | None = Field(
        default=None,
        sa_column=Column(Time(timezone=False)),
    )
    is_closed: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("false"),
        ),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


class StaffAssignmentModel(SQLModel, table=True):
    __tablename__ = "staff_assignments"
    __table_args__ = (
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= assigned_at",
            name="ck_staff_assignments_dates",
        ),
        UniqueConstraint(
            "user_id",
            "branch_id",
            "role_id",
            name="uq_staff_assignments_user_branch_role",
        ),
        UniqueConstraint(
            "branch_id",
            "employee_code",
            name="uq_staff_assignments_branch_employee_code",
        ),
        Index(
            "ix_staff_assignments_user_active",
            "user_id",
            postgresql_where=text("is_active IS TRUE"),
        ),
        Index(
            "ix_staff_assignments_branch_active",
            "branch_id",
            postgresql_where=text("is_active IS TRUE"),
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
            ForeignKey("users.id", ondelete="RESTRICT"),
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
    role_id: int = Field(
        sa_column=Column(
            SmallInteger,
            ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    employee_code: str = Field(sa_column=Column(String(40), nullable=False))
    is_active: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("true"),
        ),
    )
    assigned_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    ended_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
