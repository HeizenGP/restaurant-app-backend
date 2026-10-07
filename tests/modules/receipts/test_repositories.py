import asyncio
from dataclasses import asdict, replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.receipts.application.ports import FiscalIssuanceRequest
from app.modules.receipts.infrastructure.persistence.repositories import (
    SQLAlchemyFiscalDocumentRepository,
)
from tests.modules.admin.test_repositories import result
from tests.modules.extras_factories import receipt_setup
from tests.modules.extras_support import NOW
from tests.modules.receipts.test_services import requested


def document_and_attempt():
    async def prepare():
        s = receipt_setup()
        doc = await requested(s)
        attempt = await s.repo.reserve_attempt(doc, "a" * 64, "test_fiscal", NOW)
        await s.repo.commit()
        request = FiscalIssuanceRequest(
            document_id=doc.id,
            attempt_id=attempt.id,
            document_type=doc.document_type,
            amount=doc.amount,
            currency_code="PEN",
            recipient_document_type=None,
            recipient_document_number=None,
            recipient_name=None,
            recipient_address=None,
        )
        return s.repo.docs[doc.id], attempt, s.gateway.result(request)

    return asyncio.run(prepare())


def test_customer_branch_scoped_reads_and_active_attempt_queries():
    session = AsyncMock()
    session.execute.return_value = result()
    repo = SQLAlchemyFiscalDocumentRepository(session)
    customer, order, branch, id_ = uuid4(), uuid4(), uuid4(), uuid4()
    asyncio.run(repo.customer_document(customer, order))
    sql, params = session.execute.await_args.args
    assert "customer_id=:customer" in str(sql) and params == {
        "customer": customer,
        "order": order,
    }
    asyncio.run(repo.branch_document(branch, id_, lock=True))
    assert "branch_id=:branch AND id=:id FOR UPDATE" in str(
        session.execute.await_args.args[0]
    )
    asyncio.run(repo.active_attempt(id_))
    assert "status IN ('CREATED','PROCESSING')" in str(
        session.execute.await_args.args[0]
    )
    asyncio.run(repo.find_attempt(id_, "a" * 64))
    assert session.execute.await_args.args[1] == {"id": id_, "key": "a" * 64}


def test_reservation_inserts_attempt_then_document_processing_without_implicit_commit():
    doc, attempt, _ = document_and_attempt()
    session = AsyncMock()
    session.execute.side_effect = [result(mapping=asdict(attempt)), result()]
    repo = SQLAlchemyFiscalDocumentRepository(session)
    asyncio.run(repo.reserve_attempt(doc, "a" * 64, "test_fiscal", NOW))
    calls = session.execute.await_args_list
    assert "INSERT INTO fiscal_document_attempts" in str(calls[0].args[0])
    assert calls[0].args[1]["key"] == "a" * 64
    assert "status='PROCESSING'" in str(calls[1].args[0])
    session.commit.assert_not_called()


@pytest.mark.parametrize("attempt_status", ["SUCCEEDED", "FAILED"])
def test_old_attempt_fenced_after_document_then_attempt_lock_no_updates(attempt_status):
    doc, attempt, event = document_and_attempt()
    session = AsyncMock()
    session.execute.side_effect = [
        result(mapping=asdict(replace(doc, status="ISSUED"))),
        result(mapping=asdict(replace(attempt, status=attempt_status))),
    ]
    saved = asyncio.run(
        SQLAlchemyFiscalDocumentRepository(session).finish_attempt(
            doc, attempt, event, NOW
        )
    )
    assert saved.status == "ISSUED"
    calls = session.execute.await_args_list
    assert len(calls) == 2 and "fiscal_documents" in str(calls[0].args[0])
    assert "FOR UPDATE" in str(calls[0].args[0]) and "FOR UPDATE" in str(
        calls[1].args[0]
    )


def test_atomic_finalization_preserves_money_and_sanitizes_failure():
    doc, attempt, event = document_and_attempt()
    event = replace(
        event, status="FAILED", failure_code="private address and provider payload"
    )
    session = AsyncMock()
    session.execute.side_effect = [
        result(mapping=asdict(doc)),
        result(mapping=asdict(attempt)),
        result(),
        result(),
        result(mapping=asdict(replace(doc, status="FAILED"))),
    ]
    assert (
        asyncio.run(
            SQLAlchemyFiscalDocumentRepository(session).finish_attempt(
                doc, attempt, event, NOW
            )
        ).status
        == "FAILED"
    )
    calls = session.execute.await_args_list
    assert calls[2].args[1]["failure"] == "PROVIDER_REJECTED"
    assert calls[2].args[1]["completed"] == NOW and calls[3].args[1]["series"] is None
    assert all("amount=" not in str(call.args[0]) for call in calls)
    assert not any("private" in str(call.args) for call in calls)
    session.commit.assert_not_called()
