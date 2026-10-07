"""Operational histories owned by Fulfillment; Alembic-only DDL."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class DeliveryAssignmentModel(SQLModel, table=True):
    __tablename__ = "delivery_assignments"
    __table_args__ = (
        CheckConstraint(
            "NOT (unassigned_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_delivery_assignments_terminal",
        ),
        CheckConstraint(
            "(unassigned_at IS NULL) = (unassigned_by_user_id IS NULL)",
            name="ck_delivery_assignments_actor",
        ),
        CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at",
            name="ck_delivery_assignments_unassigned_time",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= assigned_at",
            name="ck_delivery_assignments_completed_time",
        ),
        Index(
            "uq_delivery_assignments_active",
            "order_id",
            unique=True,
            postgresql_where=text("unassigned_at IS NULL AND completed_at IS NULL"),
        ),
        Index("ix_delivery_assignments_history", "order_id", "assigned_at", "id"),
        Index("ix_delivery_assignments_staff", "assigned_user_id", "assigned_at", "id"),
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
    assigned_user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    assigned_by_user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    assigned_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    unassigned_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    unassigned_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reason: str | None = Field(
        default=None, sa_column=Column(String(200), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )


class DeliveryDelayIncidentModel(SQLModel, table=True):
    __tablename__ = "delivery_delay_incidents"
    __table_args__ = (
        CheckConstraint(
            "delay_threshold_seconds = 900 AND delay_seconds_at_detection > "
            "delay_threshold_seconds",
            name="ck_delivery_delay_incidents_threshold",
        ),
        CheckConstraint(
            "observed_order_status IN "
            "('WAITING','PREPARING','READY','OUT_FOR_DELIVERY','DELIVERED')",
            name="ck_delivery_delay_incidents_observed",
        ),
        CheckConstraint(
            "decision_status IN ('OPEN','APPROVED','REJECTED')",
            name="ck_delivery_delay_incidents_status",
        ),
        CheckConstraint(
            "(decision_status = 'OPEN' AND evaluated_at IS NULL AND "
            "evaluated_by_user_id IS NULL AND customer_responsibility IS NULL "
            "AND evaluation_note IS NULL AND remediation_description IS NULL) "
            "OR (decision_status IN ('APPROVED','REJECTED') AND evaluated_at "
            "IS NOT NULL AND evaluated_by_user_id IS NOT NULL AND evaluated_at "
            ">= detected_at)",
            name="ck_delivery_delay_incidents_evaluation",
        ),
        CheckConstraint(
            "(decision_status = 'APPROVED' AND remediation_description IS NOT "
            "NULL AND length(btrim(remediation_description)) BETWEEN 1 AND "
            "2000) OR (decision_status <> 'APPROVED' AND "
            "remediation_description IS NULL)",
            name="ck_delivery_delay_incidents_remediation",
        ),
        CheckConstraint(
            "evaluation_note IS NULL OR length(btrim(evaluation_note)) BETWEEN "
            "1 AND 2000",
            name="ck_delivery_delay_incidents_note",
        ),
        UniqueConstraint("order_id", name="uq_delivery_delay_incidents_order"),
        Index(
            "ix_delivery_delay_incidents_review",
            "branch_id",
            "decision_status",
            "detected_at",
            "id",
        ),
        Index("ix_delivery_delay_incidents_recent", "branch_id", "detected_at", "id"),
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
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    committed_eta: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    delay_threshold_seconds: int = Field(
        default=900,
        sa_column=Column(Integer(), nullable=False, server_default=text("900")),
    )
    detected_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    observed_order_status: str = Field(sa_column=Column(String(24), nullable=False))
    delay_seconds_at_detection: int = Field(sa_column=Column(Integer(), nullable=False))
    decision_status: str = Field(
        default="OPEN",
        sa_column=Column(String(10), nullable=False, server_default=text("'OPEN'")),
    )
    evaluated_by_user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    evaluated_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    customer_responsibility: bool | None = Field(
        default=None, sa_column=Column(Boolean(), nullable=True)
    )
    evaluation_note: str | None = Field(
        default=None, sa_column=Column(Text(), nullable=True)
    )
    remediation_description: str | None = Field(
        default=None, sa_column=Column(Text(), nullable=True)
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
