import asyncio
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.receipts.application.errors import FiscalProviderUnavailable
from app.modules.receipts.domain.policies import fiscal_request, paid_order
from app.modules.receipts.infrastructure.fiscal_gateway import (
    UnconfiguredFiscalDocumentGateway,
)
from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
)
from tests.modules.extras_factories import receipt_setup
from tests.modules.extras_support import NOW, principal

BOLETA = {"document_type": "BOLETA"}
FACTURA = {
    "document_type": "FACTURA",
    "recipient_document_type": "RUC",
    "recipient_document_number": "20123456789",
    "recipient_name": "TEST Company",
    "recipient_address": "TEST Fiscal address",
}


async def requested(s):
    return await s.service.request(s.customer, s.orders.order.id, "receipt-1", BOLETA)


@pytest.mark.parametrize("guest", [True, False])
@pytest.mark.parametrize("body", [BOLETA, FACTURA])
def test_request_paid_owner_historical_money_and_get_privacy(guest, body):
    async def verify():
        s = receipt_setup(customer=principal(guest=guest))
        doc = await s.service.request(s.customer, s.orders.order.id, "one", body)
        assert doc.amount == Decimal("47.00") and isinstance(doc.amount, Decimal)
        assert doc.currency_code == "PEN" and doc.status == "PENDING"
        assert doc.series is doc.number is doc.issued_at is None
        assert s.gateway.calls == 0 and not s.repo.attempts and s.orders.locks == [True]
        assert await s.service.get(s.customer, doc.order_id) == doc
        with pytest.raises(NotFoundError):
            await s.service.get(principal(guest=True), doc.order_id)
        with pytest.raises(NotFoundError):
            await s.service.request(principal(), doc.order_id, "one", body)

    asyncio.run(verify())


@pytest.mark.parametrize(
    "changes",
    [
        {"payment_status": "PENDING"},
        {"payment_status": "REFUNDED"},
        {"ledger_status": None},
        {"ledger_status": "REFUNDED"},
        {"paid_amount": None},
        {"paid_amount": Decimal("46.99")},
        {"paid_amount": Decimal("NaN")},
        {"paid_amount": 47.0},
        {"total": Decimal("-1"), "paid_amount": Decimal("-1")},
        {"total": Decimal("10000000000"), "paid_amount": Decimal("10000000000")},
        {"status": "CANCELLED"},
    ],
)
def test_unpaid_refunded_cancelled_or_inconsistent_ledger_not_requestable(changes):
    async def verify():
        s = receipt_setup()
        s.orders.order = replace(s.orders.order, **changes)
        assert not paid_order(s.orders.order)
        with pytest.raises(ConflictError) as error:
            await requested(s)
        assert error.value.code == "FISCAL_DOCUMENT_INVALID_STATE"
        assert not s.repo.docs and not s.repo.attempts

    asyncio.run(verify())


def test_request_canonical_idempotence_payload_conflict_and_cancel_preserves_history():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        assert await requested(s) == doc
        assert (
            len(doc.request_key_hash) == 64 and "receipt-1" not in doc.request_key_hash
        )
        with pytest.raises(ConflictError) as error:
            await s.service.request(s.customer, doc.order_id, "receipt-1", FACTURA)
        assert error.value.code == "RECEIPT_IDEMPOTENCY_CONFLICT"
        with pytest.raises(ConflictError) as error:
            await s.service.request(s.customer, doc.order_id, "different", BOLETA)
        assert error.value.code == "FISCAL_DOCUMENT_ALREADY_EXISTS"
        s.orders.order = replace(
            s.orders.order, status="CANCELLED", payment_status="REFUNDED"
        )
        assert (
            await requested(s) == doc
            and await s.service.get(s.customer, doc.order_id) == doc
        )
        assert len(s.repo.docs) == 1
        one, a = fiscal_request({**FACTURA, "recipient_name": " TEST Company "})
        two, b = fiscal_request(FACTURA)
        assert one == two and a == b

    asyncio.run(verify())


@pytest.mark.parametrize(
    "changes",
    [
        {"document_type": "OTHER"},
        {"amount": "0"},
        {"status": "ISSUED"},
        {"recipient_document_type": "DNI"},
        {"recipient_document_number": "123"},
        {"recipient_document_number": "abcdefghijk"},
        {"recipient_document_number": "２０１２３４５６７８９"},
        {"recipient_name": None},
        {"recipient_address": None},
        {"recipient_name": "<script>unsafe</script>\x00"},
        {"recipient_document_number": "20123456789\n"},
        {"recipient_address": "x" * 1001},
    ],
)
def test_invalid_factura_and_server_owned_fields(changes):
    with pytest.raises(ValueError):
        fiscal_request({**FACTURA, **changes})


@pytest.mark.parametrize("key", ["", "x" * 129, "with space", "line\nbreak", "ñ"])
def test_invalid_idempotency_keys(key):
    async def verify():
        s = receipt_setup()
        with pytest.raises(RequestDataError):
            await s.service.request(s.customer, s.orders.order.id, key, BOLETA)
        assert not s.repo.docs

    asyncio.run(verify())


def test_unconfigured_gateway_never_mutates_pending_or_invents_issuance():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        s.service.gateway = UnconfiguredFiscalDocumentGateway()
        with pytest.raises(FiscalProviderUnavailable) as error:
            await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert error.value.code == "FISCAL_PROVIDER_UNAVAILABLE"
        assert (
            s.repo.docs[doc.id] == doc and not s.repo.attempts and not s.audit.records
        )

    asyncio.run(verify())


def test_success_verified_only_test_gateway_reservation_commit_and_terminal_noop():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        result = await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert result.status == "ISSUED" and result.issued_at == NOW
        assert s.gateway.calls == 1 and s.gateway.lookups == 0
        assert (
            len(s.repo.attempts) == 1
            and next(iter(s.repo.attempts.values())).status == "SUCCEEDED"
        )
        assert len(s.audit.records) == 1
        assert s.audit.records[0].after_state == {"status": "PROCESSING"}
        assert await s.service.process(s.admin, s.branch, doc.id, "attempt-2") == result
        assert s.gateway.calls == 1 and len(s.repo.attempts) == 1
        s.orders.order = replace(
            s.orders.order, status="CANCELLED", payment_status="REFUNDED"
        )
        assert await s.service.get(s.customer, doc.order_id) == result

    asyncio.run(verify())


def test_unknown_outcome_same_key_reconciles_no_second_issue_different_key_blocked():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        s.gateway.unknown = True
        with pytest.raises(FiscalProviderUnavailable):
            await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert s.repo.docs[doc.id].status == "PROCESSING" and len(s.repo.attempts) == 1
        with pytest.raises(ConflictError):
            await s.service.process(s.admin, s.branch, doc.id, "attempt-2")
        s.gateway.unknown = False
        result = await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert result.status == "ISSUED" and s.gateway.calls == s.gateway.lookups == 1
        assert len(s.audit.records) == 1

    asyncio.run(verify())


def test_finalization_failure_rolls_back_both_records_then_lookup_recovers():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        s.repo.fail_finish = True
        with pytest.raises(RuntimeError):
            await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert s.repo.docs[doc.id].status == "PROCESSING"
        assert next(iter(s.repo.attempts.values())).status == "PROCESSING"
        s.repo.fail_finish = False
        result = await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert result.status == "ISSUED" and s.gateway.calls == s.gateway.lookups == 1

    asyncio.run(verify())


def test_failed_attempt_same_key_noop_new_key_retries_and_old_fence_cannot_overwrite():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        s.gateway.result_status = "FAILED"
        failed = await s.service.process(s.admin, s.branch, doc.id, "attempt-1")
        assert failed.status == "FAILED"
        old = next(iter(s.repo.attempts.values()))
        assert await s.service.process(s.admin, s.branch, doc.id, "attempt-1") == failed
        assert s.gateway.calls == 1
        s.gateway.result_status = "ISSUED"
        issued = await s.service.process(s.admin, s.branch, doc.id, "attempt-2")
        assert issued.status == "ISSUED" and len(s.repo.attempts) == 2
        # Late response for an already terminal attempt cannot modify the new outcome.
        from app.modules.receipts.application.ports import FiscalIssuanceRequest

        request = FiscalIssuanceRequest(
            document_id=doc.id,
            attempt_id=old.id,
            document_type="BOLETA",
            amount=doc.amount,
            currency_code="PEN",
            recipient_document_type=None,
            recipient_document_number=None,
            recipient_name=None,
            recipient_address=None,
        )
        late = replace(s.gateway.result(request), status="FAILED")
        assert await s.repo.finish_attempt(doc, old, late, NOW) == issued
        await s.repo.commit()

    asyncio.run(verify())


@pytest.mark.parametrize(
    "changes",
    [
        {"verified": False},
        {"verified": "yes"},
        {"document_id": uuid4()},
        {"attempt_id": uuid4()},
        {"provider_code": "unknown"},
        {"status": "SUCCEEDED"},
        {"amount": Decimal("1")},
        {"amount": 47.0},
        {"amount": Decimal("NaN")},
        {"currency_code": "USD"},
        {"issued_at": None},
        {"issued_at": datetime(2026, 10, 7)},
        {"series": ""},
        {"number": "x" * 65},
        {"provider_reference": " raw "},
        {"provider_reference": "x\x00"},
        {"provider_reference": "x" * 256},
    ],
)
def test_unverified_or_mismatched_gateway_result_is_not_issued(changes):
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        original = s.gateway.result
        s.gateway.result = lambda request: replace(original(request), **changes)
        with pytest.raises(FiscalProviderUnavailable):
            await s.service.process(s.admin, s.branch, doc.id, "attempt")
        assert s.repo.docs[doc.id].status == "PROCESSING"
        assert next(iter(s.repo.attempts.values())).status == "PROCESSING"

    asyncio.run(verify())


@pytest.mark.parametrize("status", ["FAILED", "PROCESSING"])
def test_invalid_provider_reference_checked_for_non_issued_results(status):
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        original = s.gateway.result
        s.gateway.result = lambda request: replace(
            original(request), status=status, provider_reference="x" * 256
        )
        with pytest.raises(FiscalProviderUnavailable):
            await s.service.process(s.admin, s.branch, doc.id, "attempt")
        assert s.repo.docs[doc.id].status == "PROCESSING"

    asyncio.run(verify())


def test_admin_scope_revocation_foreign_id_and_filtered_read_no_external_call():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        rows = await s.service.list(
            s.admin, s.branch, from_date=date(2026, 1, 1), to_date=date(2026, 12, 31)
        )
        assert rows == [doc]
        assert await s.service.list(s.admin, s.branch, status="ISSUED") == []
        with pytest.raises(ForbiddenError):
            await s.service.process(s.customer, s.branch, doc.id, "one")
        with pytest.raises(ForbiddenError):
            await s.service.list(s.admin, uuid4())
        with pytest.raises(NotFoundError):
            await s.service.process(s.admin, s.branch, uuid4(), "one")
        s.authorization.enabled = False
        with pytest.raises(ForbiddenError):
            await s.service.process(s.admin, s.branch, doc.id, "one")
        assert s.gateway.calls == 0 and not s.repo.attempts

    asyncio.run(verify())


def test_permission_rechecked_after_document_lock():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        original = s.repo.branch_document

        async def revoked(*args, **kwargs):
            result = await original(*args, **kwargs)
            s.authorization.enabled = False
            return result

        s.repo.branch_document = revoked
        with pytest.raises(ForbiddenError):
            await s.service.process(s.admin, s.branch, doc.id, "one")
        assert not s.repo.attempts and s.gateway.calls == 0

    asyncio.run(verify())


def test_audit_failure_rolls_back_reservation_before_provider():
    async def verify():
        s = receipt_setup()
        doc = await requested(s)
        s.audit.fail = True
        with pytest.raises(RuntimeError):
            await s.service.process(s.admin, s.branch, doc.id, "one")
        assert (
            s.repo.docs[doc.id] == doc and not s.repo.attempts and s.gateway.calls == 0
        )

    asyncio.run(verify())
