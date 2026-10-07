from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.application.audit import AuditState
from app.shared.domain.time import utc_now


class AuditLogModel(SQLModel, table=True):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
        Index("ix_audit_logs_entity_created", "entity_type", "entity_id", "created_at"),
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
    actor_user_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    branch_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PG_UUID(as_uuid=True), ForeignKey("branches.id", ondelete="RESTRICT")
        ),
    )
    action: str = Field(sa_column=Column(String(80), nullable=False))
    entity_type: str = Field(sa_column=Column(String(80), nullable=False))
    entity_id: UUID = Field(sa_column=Column(PG_UUID(as_uuid=True), nullable=False))
    before_state: AuditState | None = Field(default=None, sa_column=Column(JSONB))
    after_state: AuditState | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        ),
    )
