"""Persistence metadata; creation is owned exclusively by Alembic."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel

from app.shared.domain.time import utc_now


class FiscalDocumentModel(SQLModel, table=True):
    __tablename__ = "fiscal_documents"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_fiscal_documents_order"),
        CheckConstraint(
            "document_type IN ('BOLETA','FACTURA')", name="ck_fiscal_documents_type"
        ),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','ISSUED','FAILED')",
            name="ck_fiscal_documents_status",
        ),
        CheckConstraint(
            "amount>=0 AND amount<>'NaN'::numeric", name="ck_fiscal_documents_amount"
        ),
        CheckConstraint("currency_code='PEN'", name="ck_fiscal_documents_currency"),
        CheckConstraint(
            "(status='ISSUED')=(issued_at IS NOT NULL) AND (status<>'ISSUED' OR "
            "(series IS NOT NULL AND number IS NOT NULL AND provider_code IS "
            "NOT NULL AND provider_reference IS NOT NULL))",
            name="ck_fiscal_documents_issue",
        ),
        CheckConstraint(
            "document_type<>'FACTURA' OR (recipient_document_type IS NOT NULL AND "
            "recipient_document_number IS NOT NULL AND recipient_document_type='RUC' "
            "AND "
            "recipient_document_number ~ '^[0-9]{11}$' AND recipient_name IS "
            "NOT NULL AND length(btrim(recipient_name))>0 AND recipient_address "
            "IS NOT NULL AND length(btrim(recipient_address))>0)",
            name="ck_fiscal_documents_factura",
        ),
        CheckConstraint(
            "request_key_hash ~ '^[a-f0-9]{64}$' AND request_fingerprint ~ "
            "'^[a-f0-9]{64}$'",
            name="ck_fiscal_documents_hashes",
        ),
        Index(
            "ix_fiscal_documents_branch_status",
            "branch_id",
            "status",
            "requested_at",
            "id",
        ),
        Index(
            "uq_fiscal_documents_number",
            "document_type",
            "series",
            "number",
            unique=True,
            postgresql_where=text("series IS NOT NULL AND number IS NOT NULL"),
        ),
        Index(
            "uq_fiscal_documents_reference",
            "provider_code",
            "provider_reference",
            unique=True,
            postgresql_where=text("provider_reference IS NOT NULL"),
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
    branch_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("branches.id", ondelete="RESTRICT"),
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
    document_type: str = Field(sa_column=Column(String(8), nullable=False))
    status: str = Field(
        default="PENDING",
        sa_column=Column(String(16), nullable=False, server_default=text("'PENDING'")),
    )
    amount: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    currency_code: str = Field(
        default="PEN",
        sa_column=Column(String(3), nullable=False, server_default=text("'PEN'")),
    )
    recipient_document_type: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    recipient_document_number: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    recipient_name: str | None = Field(
        default=None, sa_column=Column(String(180), nullable=True)
    )
    recipient_address: str | None = Field(
        default=None, sa_column=Column(Text(), nullable=True)
    )
    series: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    number: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    provider_code: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    provider_reference: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    request_key_hash: str = Field(sa_column=Column(String(64), nullable=False))
    request_fingerprint: str = Field(sa_column=Column(String(64), nullable=False))
    requested_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    issued_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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


class FiscalDocumentAttemptModel(SQLModel, table=True):
    __tablename__ = "fiscal_document_attempts"
    __table_args__ = (
        UniqueConstraint(
            "fiscal_document_id",
            "idempotency_key",
            name="uq_fiscal_document_attempts_key",
        ),
        CheckConstraint(
            "status IN ('CREATED','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_fiscal_document_attempts_status",
        ),
        CheckConstraint(
            "(status IN ('SUCCEEDED','FAILED'))=(completed_at IS NOT NULL)",
            name="ck_fiscal_document_attempts_complete",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[a-f0-9]{64}$'", name="ck_fiscal_document_attempts_key"
        ),
        CheckConstraint(
            "failure_code IS NULL OR (status='FAILED' AND failure_code ~ "
            "'^[A-Z][A-Z0-9_]{0,63}$')",
            name="ck_fiscal_document_attempts_failure",
        ),
        Index(
            "uq_fiscal_document_attempts_active",
            "fiscal_document_id",
            unique=True,
            postgresql_where=text("status IN ('CREATED','PROCESSING')"),
        ),
        Index(
            "uq_fiscal_document_attempts_reference",
            "provider_code",
            "provider_reference",
            unique=True,
            postgresql_where=text("provider_reference IS NOT NULL"),
        ),
        Index(
            "ix_fiscal_document_attempts_recent",
            "fiscal_document_id",
            "created_at",
            "id",
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
    fiscal_document_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("fiscal_documents.id", ondelete="RESTRICT"),
            nullable=False,
        )
    )
    idempotency_key: str = Field(sa_column=Column(String(64), nullable=False))
    provider_code: str = Field(sa_column=Column(String(32), nullable=False))
    provider_reference: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    status: str = Field(
        default="CREATED",
        sa_column=Column(String(16), nullable=False, server_default=text("'CREATED'")),
    )
    failure_code: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
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
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
