from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.receipts.domain.models import FiscalDocument, FiscalDocumentAttempt
from app.shared.application.administration import AdministrationConflict


class SQLAlchemyFiscalDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def customer_document(self, customer_id, order_id):
        rows = await self.session.execute(
            text(
                "SELECT * FROM fiscal_documents WHERE customer_id=:customer AND "
                "order_id=:order"
            ),
            {"customer": customer_id, "order": order_id},
        )
        row = rows.mappings().one_or_none()
        return FiscalDocument(**row) if row else None

    async def branch_document(self, branch_id, document_id, *, lock=False):
        rows = await self.session.execute(
            text(
                "SELECT * FROM fiscal_documents WHERE branch_id=:branch AND id=:id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"branch": branch_id, "id": document_id},
        )
        row = rows.mappings().one_or_none()
        return FiscalDocument(**row) if row else None

    async def create_document(self, order, key_hash, fingerprint, values, now):
        try:
            rows = await self.session.execute(
                text(
                    "INSERT INTO fiscal_documents(order_id,branch_id,"
                    "customer_id,document_type,amount,"
                    "recipient_document_type,recipient_document_number,recipient_name,recipient_address,"
                    "request_key_hash,request_fingerprint,requested_at) "
                    "VALUES (:order,:branch,:customer,:document_type,:amount,"
                    ":recipient_document_type,"
                    ":recipient_document_number,:recipient_name,"
                    ":recipient_address,:key,:fingerprint,:now) RETURNING *"
                ),
                {
                    **values,
                    "order": order.id,
                    "branch": order.branch_id,
                    "customer": order.customer_id,
                    "amount": order.paid_amount,
                    "key": key_hash,
                    "fingerprint": fingerprint,
                    "now": now,
                },
            )
        except IntegrityError:
            raise AdministrationConflict(
                "FISCAL_DOCUMENT_ALREADY_EXISTS", "Order already has a fiscal document"
            ) from None
        return FiscalDocument(**rows.mappings().one())

    async def branch_documents(
        self, branch_id, status, document_type, start, end, limit, offset
    ):
        rows = await self.session.execute(
            text(
                "SELECT * FROM fiscal_documents WHERE branch_id=:branch "
                "AND (CAST(:status AS text) IS NULL OR status=:status) "
                "AND (CAST(:type AS text) IS NULL OR document_type=:type) "
                "AND (CAST(:start AS timestamptz) IS NULL OR requested_at>=:start) "
                "AND (CAST(:end AS timestamptz) IS NULL OR requested_at<:end) "
                "ORDER BY requested_at DESC,id DESC LIMIT :limit OFFSET :offset"
            ),
            {
                "branch": branch_id,
                "status": status,
                "type": document_type,
                "start": start,
                "end": end,
                "limit": limit,
                "offset": offset,
            },
        )
        return [FiscalDocument(**row) for row in rows.mappings()]

    async def find_attempt(self, document_id, key_hash):
        rows = await self.session.execute(
            text(
                "SELECT * FROM fiscal_document_attempts WHERE "
                "fiscal_document_id=:id AND idempotency_key=:key"
            ),
            {"id": document_id, "key": key_hash},
        )
        row = rows.mappings().one_or_none()
        return FiscalDocumentAttempt(**row) if row else None

    async def active_attempt(self, document_id):
        rows = await self.session.execute(
            text(
                "SELECT * FROM fiscal_document_attempts WHERE "
                "fiscal_document_id=:id AND status IN ('CREATED','PROCESSING')"
            ),
            {"id": document_id},
        )
        row = rows.mappings().one_or_none()
        return FiscalDocumentAttempt(**row) if row else None

    async def reserve_attempt(self, document, key_hash, provider, now):
        rows = await self.session.execute(
            text(
                "INSERT INTO fiscal_document_attempts(id,fiscal_document_id,"
                "idempotency_key,provider_code,status,created_at,updated_at) "
                "VALUES (:id,:document,:key,:provider,'PROCESSING',:now,:now) "
                "RETURNING *"
            ),
            {
                "id": uuid4(),
                "document": document.id,
                "key": key_hash,
                "provider": provider,
                "now": now,
            },
        )
        attempt = FiscalDocumentAttempt(**rows.mappings().one())
        await self.session.execute(
            text(
                "UPDATE fiscal_documents SET "
                "status='PROCESSING',provider_code=:provider WHERE id=:id"
            ),
            {"id": document.id, "provider": provider},
        )
        return attempt

    async def finish_attempt(self, document, attempt, result, now):
        locked = await self.branch_document(document.branch_id, document.id, lock=True)
        rows = await self.session.execute(
            text(
                "SELECT * FROM fiscal_document_attempts WHERE id=:id AND "
                "fiscal_document_id=:document FOR UPDATE"
            ),
            {"id": attempt.id, "document": document.id},
        )
        current = FiscalDocumentAttempt(**rows.mappings().one())
        if current.status in {"SUCCEEDED", "FAILED"}:
            return locked
        if locked.status != "PROCESSING" or current.status not in {
            "CREATED",
            "PROCESSING",
        }:
            raise AdministrationConflict(
                "FISCAL_DOCUMENT_INVALID_STATE", "Fiscal attempt is not active"
            )
        final = result.status in {"ISSUED", "FAILED"}
        attempt_status = "SUCCEEDED" if result.status == "ISSUED" else result.status
        failure = (
            result.failure_code
            if result.failure_code
            in {"PROVIDER_REJECTED", "INVALID_RECIPIENT", "REJECTED"}
            else "PROVIDER_REJECTED"
        )
        await self.session.execute(
            text(
                "UPDATE fiscal_document_attempts SET "
                "status=:status,provider_reference=:reference,"
                "failure_code=:failure,completed_at=:completed WHERE id=:id"
            ),
            {
                "id": current.id,
                "status": attempt_status,
                "reference": result.provider_reference,
                "failure": failure if result.status == "FAILED" else None,
                "completed": now if final else None,
            },
        )
        await self.session.execute(
            text(
                "UPDATE fiscal_documents SET "
                "status=:status,provider_reference=:reference,"
                "series=:series,number=:number,issued_at=:issued WHERE id=:id"
            ),
            {
                "id": document.id,
                "status": result.status,
                "reference": result.provider_reference,
                "series": result.series if result.status == "ISSUED" else None,
                "number": result.number if result.status == "ISSUED" else None,
                "issued": result.issued_at if result.status == "ISSUED" else None,
            },
        )
        return await self.branch_document(document.branch_id, document.id)

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
