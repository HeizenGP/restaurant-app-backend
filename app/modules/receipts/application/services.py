import re
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.orders.application.customer_records import CustomerOrderReader
from app.modules.receipts.application.errors import FiscalProviderUnavailable
from app.modules.receipts.application.ports import (
    FiscalDocumentGateway,
    FiscalDocumentRepository,
    FiscalIssuanceRequest,
)
from app.modules.receipts.domain.policies import aware_time, fiscal_request, paid_order
from app.shared.application.administration import (
    AdministrationAuthorization,
    AdministrationConflict,
    AdministrationNotFound,
    require_administration,
)
from app.shared.application.audit import AuditRecord, AuditRecorder
from app.shared.application.customer_identity import (
    customer_identity,
    idempotency_digest,
)
from app.shared.application.exceptions import RequestDataError
from app.shared.domain.calendar import calendar_bounds
from app.shared.domain.time import utc_now


class ReceiptService:
    def __init__(
        self,
        repository: FiscalDocumentRepository,
        orders: CustomerOrderReader,
        authorization: AdministrationAuthorization,
        audit: AuditRecorder,
        gateway: FiscalDocumentGateway,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.repository, self.orders, self.authorization = (
            repository,
            orders,
            authorization,
        )
        self.audit, self.gateway, self.clock = audit, gateway, clock

    async def request(
        self, principal: Principal, order_id: UUID, key: str, values: dict
    ):
        customer = customer_identity(principal)
        try:
            key_hash = idempotency_digest(key)
            try:
                values, fingerprint = fiscal_request(values)
            except ValueError:
                raise RequestDataError(
                    "Invalid fiscal recipient or document type"
                ) from None
            order = await self.orders.customer_order(customer, order_id, lock=True)
            if order is None:
                raise AdministrationNotFound("ORDER_NOT_FOUND", "Order not found")
            existing = await self.repository.customer_document(customer, order_id)
            if existing:
                if existing.request_key_hash != key_hash:
                    raise AdministrationConflict(
                        "FISCAL_DOCUMENT_ALREADY_EXISTS",
                        "Order already has a fiscal document",
                    )
                if existing.request_fingerprint != fingerprint:
                    raise AdministrationConflict(
                        "RECEIPT_IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key payload differs",
                    )
                await self.repository.commit()
                return existing
            if not paid_order(order):
                raise AdministrationConflict(
                    "FISCAL_DOCUMENT_INVALID_STATE",
                    "Order must be paid and not cancelled",
                )
            result = await self.repository.create_document(
                order, key_hash, fingerprint, values, self.clock()
            )
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def get(self, principal: Principal, order_id: UUID):
        result = await self.repository.customer_document(
            customer_identity(principal), order_id
        )
        if result is None:
            raise AdministrationNotFound(
                "FISCAL_DOCUMENT_NOT_FOUND", "Fiscal document not found"
            )
        return result

    async def list(
        self,
        principal: Principal,
        branch_id: UUID,
        status=None,
        document_type=None,
        from_date=None,
        to_date=None,
        limit=50,
        offset=0,
    ):
        await require_administration(
            self.authorization, principal, branch_id, "RECEIPT_VIEW"
        )
        scopes = await self.authorization.authorized_branches(
            principal.user_id, "RECEIPT_VIEW", branch_id=branch_id
        )
        if not scopes:
            raise AdministrationNotFound("BRANCH_NOT_FOUND", "Branch not found")
        try:
            start, end = calendar_bounds(from_date, to_date, scopes[0].timezone)
        except ValueError:
            raise RequestDataError("Invalid date range") from None
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise RequestDataError("Invalid pagination")
        return await self.repository.branch_documents(
            branch_id, status, document_type, start, end, limit, offset
        )

    async def process(
        self, principal: Principal, branch_id: UUID, document_id: UUID, key: str
    ):
        try:
            actor = await require_administration(
                self.authorization, principal, branch_id, "RECEIPT_MANAGE"
            )
            key_hash = idempotency_digest(key)
            document = await self.repository.branch_document(
                branch_id, document_id, lock=True
            )
            if document is None:
                raise AdministrationNotFound(
                    "FISCAL_DOCUMENT_NOT_FOUND", "Fiscal document not found"
                )
            await require_administration(
                self.authorization, principal, branch_id, "RECEIPT_MANAGE"
            )
            if document.status == "ISSUED":
                await self.repository.commit()
                return document
            provider = self.gateway.provider_code
            if not provider or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", provider):
                raise FiscalProviderUnavailable()
            attempt = await self.repository.find_attempt(document.id, key_hash)
            retry = attempt is not None
            if attempt:
                if attempt.provider_code != provider:
                    raise AdministrationConflict(
                        "RECEIPT_IDEMPOTENCY_CONFLICT", "Attempt provider differs"
                    )
                if attempt.status == "FAILED":
                    await self.repository.commit()
                    return document
            else:
                if document.status not in {
                    "PENDING",
                    "FAILED",
                } or await self.repository.active_attempt(document.id):
                    raise AdministrationConflict(
                        "FISCAL_DOCUMENT_INVALID_STATE",
                        "Fiscal processing is already active",
                    )
                attempt = await self.repository.reserve_attempt(
                    document, key_hash, provider, self.clock()
                )
                await self.audit.record(
                    AuditRecord(
                        actor_user_id=actor,
                        branch_id=branch_id,
                        action="FISCAL_DOCUMENT_PROCESS_REQUESTED",
                        entity_type="FISCAL_DOCUMENT",
                        entity_id=document.id,
                        before_state={"status": document.status},
                        after_state={"status": "PROCESSING"},
                    )
                )
            request = FiscalIssuanceRequest(
                document_id=document.id,
                attempt_id=attempt.id,
                **{
                    k: getattr(document, k)
                    for k in (
                        "document_type",
                        "amount",
                        "currency_code",
                        "recipient_document_type",
                        "recipient_document_number",
                        "recipient_name",
                        "recipient_address",
                    )
                },
            )
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        # No session query/transaction between the preceding commit and provider return.
        try:
            result = await (
                self.gateway.lookup(request) if retry else self.gateway.issue(request)
            )
            self._validate_result(request, provider, result)
        except Exception:
            # Keep unknown outcomes PROCESSING; retries reconcile rather than reissue.
            raise FiscalProviderUnavailable() from None
        try:
            saved = await self.repository.finish_attempt(
                document, attempt, result, self.clock()
            )
            await self.repository.commit()
            return saved
        except Exception:
            await self.repository.rollback()
            raise

    @staticmethod
    def _validate_result(request, provider, result):
        if (
            result.verified is not True
            or result.document_id != request.document_id
            or result.attempt_id != request.attempt_id
            or result.provider_code != provider
            or result.status not in {"PROCESSING", "ISSUED", "FAILED"}
        ):
            raise ValueError("Unverified fiscal result")
        if result.provider_reference is not None:
            value = result.provider_reference
            if (
                not isinstance(value, str)
                or not value.strip()
                or value != value.strip()
                or len(value) > 255
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError("Invalid fiscal provider reference")
        if result.status == "ISSUED":
            if (
                not isinstance(result.amount, Decimal)
                or not result.amount.is_finite()
                or result.amount != request.amount
                or result.currency_code != request.currency_code
                or not aware_time(result.issued_at)
            ):
                raise ValueError("Fiscal result differs from paid document")
            for field, maximum in (
                ("series", 32),
                ("number", 64),
                ("provider_reference", 255),
            ):
                value = getattr(result, field)
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value) > maximum
                    or value != value.strip()
                    or any(ord(c) < 32 for c in value)
                ):
                    raise ValueError("Invalid fiscal issuance reference")
