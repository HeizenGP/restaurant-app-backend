"""Persistence metadata; creation is owned exclusively by Alembic."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class OrderReviewModel(SQLModel, table=True):
    __tablename__ = "order_reviews"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_order_reviews_order"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_order_reviews_rating"),
        CheckConstraint(
            "comment IS NULL OR length(comment)<=1000", name="ck_order_reviews_comment"
        ),
        Index("ix_order_reviews_branch_created", "branch_id", "created_at", "id"),
        Index(
            "ix_order_reviews_branch_rating", "branch_id", "rating", "created_at", "id"
        ),
    )
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(
            PG_UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
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
    rating: int = Field(sa_column=Column(SmallInteger(), nullable=False))
    comment: str | None = Field(default=None, sa_column=Column(Text(), nullable=True))
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
