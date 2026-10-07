from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    SessionDependency,
    get_current_customer,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.orders.infrastructure.customer_records import (
    SQLAlchemyCustomerOrderReader,
)
from app.modules.receipts.application.ports import FiscalDocumentGateway
from app.modules.receipts.application.services import ReceiptService
from app.modules.receipts.domain.policies import fiscal_request
from app.modules.receipts.infrastructure.fiscal_gateway import (
    UnconfiguredFiscalDocumentGateway,
)
from app.modules.receipts.infrastructure.persistence.repositories import (
    SQLAlchemyFiscalDocumentRepository,
)
from app.presentation.errors import ErrorResponse
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder

ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/orders", tags=["receipts"], responses=ERRORS)
admin_router = APIRouter(
    prefix="/admin/receipts/branches", tags=["admin receipts"], responses=ERRORS
)
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]
Key = Annotated[
    str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")
]


def get_fiscal_gateway():
    return UnconfiguredFiscalDocumentGateway()


def get_receipt_service(
    session: SessionDependency,
    gateway: Annotated[FiscalDocumentGateway, Depends(get_fiscal_gateway)],
):
    return ReceiptService(
        SQLAlchemyFiscalDocumentRepository(session),
        SQLAlchemyCustomerOrderReader(session),
        SQLAlchemyBranchRepository(session),
        SQLAlchemyAuditRecorder(session),
        gateway,
    )


Service = Annotated[ReceiptService, Depends(get_receipt_service)]


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document_type: Literal["BOLETA", "FACTURA"]
    recipient_document_type: str | None = Field(default=None, max_length=16)
    recipient_document_number: str | None = Field(default=None, max_length=32)
    recipient_name: str | None = Field(default=None, max_length=180)
    recipient_address: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def recipient(self):
        fiscal_request(self.model_dump())
        return self


class ReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    branch_id: UUID
    document_type: Literal["BOLETA", "FACTURA"]
    status: Literal["PENDING", "PROCESSING", "ISSUED", "FAILED"]
    amount: Decimal
    currency_code: Literal["PEN"]
    recipient_document_type: str | None
    recipient_document_number: str | None
    recipient_name: str | None
    recipient_address: str | None
    series: str | None
    number: str | None
    provider_code: str | None
    provider_reference: str | None
    requested_at: datetime
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReceiptQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["PENDING", "PROCESSING", "ISSUED", "FAILED"] | None = None
    document_type: Literal["BOLETA", "FACTURA"] | None = None
    from_date: date | None = None
    to_date: date | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


@router.post("/{order_id}/receipt", status_code=201, response_model=ReceiptResponse)
async def request_receipt(
    order_id: UUID,
    body: ReceiptRequest,
    key: Key,
    principal: CurrentCustomer,
    service: Service,
):
    return await service.request(principal, order_id, key, body.model_dump())


@router.get("/{order_id}/receipt", response_model=ReceiptResponse)
async def get_receipt(order_id: UUID, principal: CurrentCustomer, service: Service):
    return await service.get(principal, order_id)


@admin_router.get("/{branch_id}", response_model=list[ReceiptResponse])
async def branch_receipts(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
    query: Annotated[ReceiptQuery, Query()],
):
    return await service.list(principal, branch_id, **query.model_dump())


@admin_router.post("/{branch_id}/{receipt_id}/process", response_model=ReceiptResponse)
async def process_receipt(
    branch_id: UUID,
    receipt_id: UUID,
    key: Key,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.process(principal, branch_id, receipt_id, key)
