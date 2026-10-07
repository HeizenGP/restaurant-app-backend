from dataclasses import asdict, replace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.payments.application.refund_errors import (
    RefundConflictError,
    RefundDataError,
)
from app.modules.payments.domain.models import EventStatus, VerifiedResult
from app.modules.payments.domain.refunds import (
    RefundProviderEvent,
    RefundStatus,
    transition_refund,
)
from app.modules.payments.infrastructure.persistence.refund_models import (
    RefundModel,
    RefundProviderEventModel,
)
from app.modules.payments.infrastructure.persistence.refund_repositories import (
    SQLAlchemyRefundRepository,
    refund_domain,
)
from tests.modules.fulfillment.test_repositories import latest, session
from tests.modules.payments.fakes import NOW
from tests.modules.payments.test_refund_domain import refund

pytestmark = pytest.mark.anyio


async def test_scope_filters_before_identity_lock_does_not_lock_orders():
    db = session()
    repo = SQLAlchemyRefundRepository(db)
    await repo.scoped(uuid4(), uuid4(), lock=True)
    statement = latest(db)
    assert "orders.branch_id =" in statement and "refunds.id =" in statement
    assert (
        "FOR UPDATE OF refunds" in statement and "FOR UPDATE OF orders" not in statement
    )
    await repo.owned(uuid4(), uuid4())
    assert "orders.customer_id =" in latest(db) and "FOR UPDATE" not in latest(db)
    db.commit.assert_not_awaited()


async def test_financial_update_changes_status_only_and_is_conditional():
    db = session()
    old = refund()
    new = transition_refund(old, RefundStatus.PROCESSING, NOW)
    db.execute.return_value.scalar_one_or_none.return_value = RefundModel(**asdict(new))
    assert await SQLAlchemyRefundRepository(db).save_refund(old, new) == new
    sql = latest(db)
    assert "refunds.status =" in sql and "refunds.reconciliation_required =" in sql
    prefix = sql.split(" WHERE ")[0]
    for field in (
        "payment_id",
        "order_id",
        "amount",
        "currency_code",
        "method_type",
        "requested_at",
    ):
        assert field + "=" not in prefix
    db.commit.assert_not_awaited()


async def test_missing_conditional_row_conflicts():
    db = session()
    with pytest.raises(RefundConflictError):
        await SQLAlchemyRefundRepository(db).save_refund(refund(), refund())


async def test_capture_selects_original_success_paid_and_detects_ambiguity():
    db = session()
    with pytest.raises(RefundDataError):
        await SQLAlchemyRefundRepository(db).successful_capture(uuid4())
    statement = latest(db)
    assert "payment_attempts.status =" in statement and "payments.status =" in statement
    assert (
        "LIMIT" in statement and db.execute.call_args.args[0]._limit_clause.value == 2
    )
    assert "FOR UPDATE" not in statement


async def test_view_is_two_bounded_queries_not_n_plus_one():
    db = session()
    view = await SQLAlchemyRefundRepository(db).view(refund())
    assert not view.attempts and not view.history and db.execute.await_count == 2
    assert all(
        call.args[0]._limit_clause.value == 100 for call in db.execute.call_args_list
    )


async def test_list_is_branch_filtered_stably_sorted_paginated():
    db = session()
    await SQLAlchemyRefundRepository(db).list_branch(
        uuid4(), RefundStatus.PENDING, None, 20, 4
    )
    assert "orders.branch_id =" in latest(db) and "refunds.status =" in latest(db)
    assert "ORDER BY refunds.requested_at, refunds.id" in latest(db)
    assert (
        "LIMIT" in latest(db)
        and "OFFSET" in latest(db)
        and "FOR UPDATE" not in latest(db)
    )


async def test_provider_event_insert_does_not_overwrite_existing_evidence():
    db = session()
    e = RefundProviderEvent(
        provider_code="test_gateway",
        provider_event_id="evt",
        provider_reference="ref",
        payload_hash="a" * 64,
        result=VerifiedResult.SUCCEEDED,
        reported_amount=refund().amount,
        reported_currency="PEN",
        provider_occurred_at=NOW,
        received_at=NOW,
    )
    db.execute.return_value.scalar_one_or_none.return_value = RefundProviderEventModel(
        **asdict(e)
    )
    assert await SQLAlchemyRefundRepository(db).get_or_insert_event(e) == e
    assert (
        "ON CONFLICT ON CONSTRAINT uq_refund_provider_events_key DO NOTHING"
        in latest(db)
    )
    assert "DO UPDATE" not in latest(db)


async def test_event_update_preserves_verified_payload_and_hash():
    db = session()
    e = RefundProviderEvent(
        provider_code="test_gateway",
        provider_event_id="evt",
        provider_reference="ref",
        payload_hash="a" * 64,
        result=VerifiedResult.SUCCEEDED,
        reported_amount=refund().amount,
        reported_currency="PEN",
        provider_occurred_at=NOW,
        received_at=NOW,
    )
    changed = replace(e, processing_status=EventStatus.PROCESSED, processed_at=NOW)
    db.execute.return_value.scalar_one_or_none.return_value = e.id
    await SQLAlchemyRefundRepository(db).save_event(e, changed)
    sql = latest(db)
    assert "payload_hash =" in sql and "processing_status =" in sql
    for key in (
        "payload_hash",
        "reported_amount",
        "reported_currency",
        "provider_event_id",
        "provider_reference",
        "result",
    ):
        assert key + "=" not in sql.split(" WHERE ")[0]


async def test_safe_integrity_error_and_rollback():
    db = session()
    db.flush.side_effect = IntegrityError(
        "PRIVATE SQL", {}, RuntimeError("PRIVATE constraint")
    )
    repo = SQLAlchemyRefundRepository(db)
    with pytest.raises(RefundConflictError) as error:
        await repo.insert_refund(refund())
    assert "PRIVATE" not in str(error.value)
    await repo.rollback()
    db.rollback.assert_awaited_once()


def test_corrupt_refund_is_safe_503():
    row = RefundModel(**(asdict(refund()) | {"status": "REFUNDED"}))
    with pytest.raises(RefundDataError):
        refund_domain(row)
