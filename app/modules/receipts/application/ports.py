from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app.modules.receipts.domain.models import FiscalDocument, FiscalDocumentAttempt


@dataclass(frozen=True)
class FiscalIssuanceRequest:
    document_id: UUID
    attempt_id: UUID
    document_type: str
    amount: Decimal
    currency_code: str
    recipient_document_type: str | None
    recipient_document_number: str | None
    recipient_name: str | None
    recipient_address: str | None


@dataclass(frozen=True)
class FiscalResult:
    document_id: UUID
    attempt_id: UUID
    provider_code: str
    status: str
    verified: bool
    amount: Decimal | None = None
    currency_code: str | None = None
    series: str | None = None
    number: str | None = None
    provider_reference: str | None = None
    issued_at: datetime | None = None
    failure_code: str | None = None


class FiscalDocumentGateway(Protocol):
    provider_code: str | None

    async def issue(self, request: FiscalIssuanceRequest) -> FiscalResult: ...
    async def lookup(self, request: FiscalIssuanceRequest) -> FiscalResult: ...


class FiscalDocumentRepository(Protocol):
    async def customer_document(
        self, customer_id: UUID, order_id: UUID
    ) -> FiscalDocument | None: ...
    async def branch_document(
        self, branch_id: UUID, document_id: UUID, *, lock: bool = False
    ) -> FiscalDocument | None: ...
    async def create_document(
        self, order, key_hash: str, fingerprint: str, values: dict, now: datetime
    ) -> FiscalDocument: ...
    async def branch_documents(
        self,
        branch_id: UUID,
        status: str | None,
        document_type: str | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> list[FiscalDocument]: ...
    async def find_attempt(
        self, document_id: UUID, key_hash: str
    ) -> FiscalDocumentAttempt | None: ...
    async def active_attempt(
        self, document_id: UUID
    ) -> FiscalDocumentAttempt | None: ...
    async def reserve_attempt(
        self, document: FiscalDocument, key_hash: str, provider: str, now: datetime
    ) -> FiscalDocumentAttempt: ...
    async def finish_attempt(
        self,
        document: FiscalDocument,
        attempt: FiscalDocumentAttempt,
        result: FiscalResult,
        now: datetime,
    ) -> FiscalDocument: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
