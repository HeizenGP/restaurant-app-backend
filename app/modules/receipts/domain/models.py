from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class FiscalDocument:
    id: UUID
    order_id: UUID
    branch_id: UUID
    customer_id: UUID
    document_type: str
    status: str
    amount: Decimal
    currency_code: str
    recipient_document_type: str | None
    recipient_document_number: str | None
    recipient_name: str | None
    recipient_address: str | None
    series: str | None
    number: str | None
    provider_code: str | None
    provider_reference: str | None
    request_key_hash: str
    request_fingerprint: str
    requested_at: datetime
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class FiscalDocumentAttempt:
    id: UUID
    fiscal_document_id: UUID
    idempotency_key: str
    provider_code: str
    provider_reference: str | None
    status: str
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
