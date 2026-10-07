"""Phase 8 historical records; schema changes belong exclusively to Alembic."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class CancellationRequestModel(SQLModel, table=True):
    __tablename__ = "cancellation_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED')",
            name="ck_cancellation_requests_status",
        ),
        CheckConstraint(
            "length(btrim(reason)) BETWEEN 1 AND 1000 AND reason !~ '[<>[:cntrl:]]'",
            name="ck_cancellation_requests_reason",
        ),
        CheckConstraint(
            "evaluation_note IS NULL OR (length(btrim(evaluation_note)) BETWEEN 1 AND "
            "2000 AND evaluation_note !~ '[<>[:cntrl:]]')",
            name="ck_cancellation_requests_note",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND evaluated_by_user_id IS NULL AND evaluated_at IS "
            "NULL AND evaluation_note IS NULL) OR (status IN ('APPROVED','REJECTED') "
            "AND evaluated_by_user_id IS NOT NULL AND evaluated_at IS NOT NULL AND "
            "evaluated_at >= requested_at)",
            name="ck_cancellation_requests_evaluation",
        ),
        Index(
            "uq_cancellation_requests_pending",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "ix_cancellation_requests_owner",
            "customer_id",
            "order_id",
            "requested_at",
            "id",
        ),
        Index(
            "ix_cancellation_requests_review",
            "branch_id",
            "status",
            "requested_at",
            "id",
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
    reason: str = Field(sa_column=Column(Text(), nullable=False))
    status: str = Field(
        default="PENDING",
        sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'")),
    )
    requested_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
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
    evaluation_note: str | None = Field(
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


class OrderCancellationModel(SQLModel, table=True):
    __tablename__ = "order_cancellations"
    __table_args__ = (
        CheckConstraint(
            "source IN ('ADMIN','CUSTOMER_REQUEST')",
            name="ck_order_cancellations_source",
        ),
        CheckConstraint(
            "reason_code IN ('OUT_OF_STOCK','OTHER','CUSTOMER_REQUEST')",
            name="ck_order_cancellations_reason",
        ),
        CheckConstraint(
            "(source = 'CUSTOMER_REQUEST' AND cancellation_request_id IS NOT NULL AND "
            "reason_code = 'CUSTOMER_REQUEST') OR (source = 'ADMIN' AND reason_code "
            "IN ('OUT_OF_STOCK','OTHER') AND cancellation_request_id IS NULL)",
            name="ck_order_cancellations_provenance",
        ),
        CheckConstraint(
            "(reason_code <> 'OTHER' OR reason_text IS NOT NULL) AND (reason_text IS "
            "NULL OR (length(btrim(reason_text)) BETWEEN 1 AND 1000 AND reason_text "
            "!~ '[<>[:cntrl:]]'))",
            name="ck_order_cancellations_text",
        ),
        UniqueConstraint("order_id", name="uq_order_cancellations_order"),
        UniqueConstraint(
            "cancellation_request_id", name="uq_order_cancellations_request"
        ),
        Index("ix_order_cancellations_branch", "branch_id", "cancelled_at", "id"),
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
    cancellation_request_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("cancellation_requests.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    source: str = Field(sa_column=Column(String(20), nullable=False))
    reason_code: str = Field(sa_column=Column(String(32), nullable=False))
    reason_text: str | None = Field(
        default=None, sa_column=Column(Text(), nullable=True)
    )
    cancelled_by_user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    cancelled_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
