from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Header, Path, Query, Request

from app.modules.auth.presentation.dependencies import CurrentRegisteredUser
from app.modules.payments.application.errors import PaymentEventInvalidError
from app.modules.payments.application.services import MAX_WEBHOOK_BYTES
from app.modules.payments.presentation.dependencies import (
    CurrentCustomer,
    PaymentServiceDependency,
)
from app.modules.payments.presentation.schemas import (
    EmptyRequest,
    OnlineResponse,
    PaymentResponse,
    WebhookAcknowledgement,
)
from app.presentation.errors import ErrorResponse

responses = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/payments", tags=["payments"], responses=responses)
admin_router = APIRouter(
    prefix="/admin/payments", tags=["admin payments"], responses=responses
)
EmptyQuery = Annotated[EmptyRequest, Query()]
Key = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


@router.get("/orders/{order_id}", response_model=PaymentResponse)
async def get_payment(
    order_id: UUID,
    principal: CurrentCustomer,
    service: PaymentServiceDependency,
    query: EmptyQuery,
) -> PaymentResponse:
    """Read your payment; 404 if no ledger has been created yet. No writes."""
    return PaymentResponse.from_view(await service.get(principal, order_id))


@router.post("/orders/{order_id}/online", response_model=OnlineResponse)
async def initiate_online(
    order_id: UUID,
    principal: CurrentCustomer,
    service: PaymentServiceDependency,
    idempotency_key: Key,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> OnlineResponse:
    """Reserve/replay a provider attempt, NOT a payment confirmation.
    Amount and currency come exclusively from the historical order.
    An unconfigured provider returns 503 without creating a new attempt.
    A declined attempt is returned as FAILED; use a new key to retry.
    """
    return OnlineResponse.from_result(
        await service.initiate_online(principal, order_id, idempotency_key)
    )


@admin_router.post(
    "/branches/{branch_id}/orders/{order_id}/cash/confirm",
    response_model=PaymentResponse,
)
async def confirm_cash(
    branch_id: UUID,
    order_id: UUID,
    principal: CurrentRegisteredUser,
    service: PaymentServiceDependency,
    query: EmptyQuery,
    body: Annotated[EmptyRequest | None, Body()] = None,
) -> PaymentResponse:
    """Actual cash receipt, with PAYMENT_CASH_MANAGE in this branch.
    This does not replace Orders' independent confirm-cash-release operation.
    """
    return PaymentResponse.from_view(
        await service.confirm_cash(principal, branch_id, order_id)
    )


@router.post(
    "/webhooks/{provider_code}",
    response_model=WebhookAcknowledgement,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                    "description": (
                        "Opaque provider payload. The adapter authenticates "
                        "raw bytes before parsing financial data."
                    ),
                }
            },
        }
    },
)
async def receive_webhook(
    request: Request,
    provider_code: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_-]{0,31}$")],
    service: PaymentServiceDependency,
    query: EmptyQuery,
) -> WebhookAcknowledgement:
    """No JWT. Adapter verification is mandatory, before any database lookup/write.
    No provider is configured yet: this endpoint fails closed with 503.
    Financially rejected but authenticated events are audited and acknowledged.
    Unknown references are audited with 503 pending correlation, to request retry.
    """
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_WEBHOOK_BYTES:
            raise PaymentEventInvalidError()
        raw.extend(chunk)
    await service.webhook(provider_code, bytes(raw), request.headers)
    return WebhookAcknowledgement()
