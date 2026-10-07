from dataclasses import asdict
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.cancellations.application.errors import CancellationConflictError
from app.modules.cancellations.domain.models import RequestStatus
from app.modules.cancellations.domain.policies import decide_request
from app.modules.cancellations.infrastructure.persistence.models import (
    CancellationRequestModel,
)
from app.modules.cancellations.infrastructure.persistence.repositories import (
    SQLAlchemyCancellationRepository,
    request_domain,
)
from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.infrastructure.cancellations import (
    SQLAlchemyOrderCancellationRepository,
)
from app.shared.application.exceptions import DependencyUnavailableError
from tests.modules.cancellations.fakes import cancellation_setup
from tests.modules.cancellations.test_domain import request
from tests.modules.fulfillment.test_repositories import latest, session
from tests.modules.payments.fakes import NOW

pytestmark = pytest.mark.anyio


async def test_order_lock_is_minimal_scope_filtered_and_order_owned():
    db = session()
    await SQLAlchemyOrderCancellationRepository(db).context(
        uuid4(), branch_id=uuid4(), lock=True
    )
    statement = latest(db)
    assert "orders.branch_id =" in statement and "orders.id =" in statement
    assert "FOR UPDATE OF orders" in statement
    for extra in (
        "customer_addresses",
        "products",
        "orders.idempotency_key",
        "password_hash",
        "payments",
    ):
        assert extra not in statement
    db.commit.assert_not_awaited()


async def test_owned_projection_is_scoped_by_customer():
    db = session()
    await SQLAlchemyOrderCancellationRepository(db).context(
        uuid4(), customer_id=uuid4()
    )
    assert "orders.customer_id =" in latest(db) and "FOR UPDATE" not in latest(db)


async def test_cancel_only_changes_status_and_appends_existing_history():
    db = session()
    order = cancellation_setup().order
    db.execute.return_value.scalar_one_or_none.return_value = order.id
    await SQLAlchemyOrderCancellationRepository(db).cancel(
        order, uuid4(), NOW, "Order cancelled by administrator: OUT_OF_STOCK"
    )
    statement = latest(db)
    assert statement.startswith("UPDATE orders SET status=")
    assert "orders.status =" in statement and "orders.payment_status =" in statement
    assert (
        "total=" not in statement
        and "payment_status=" not in statement.split(" WHERE ")[0]
    )
    assert db.add.call_args.args[0].to_status == "CANCELLED"
    db.commit.assert_not_awaited()


async def test_conditional_cancel_conflict_has_no_history():
    db = session()
    with pytest.raises(OrderConflictError):
        await SQLAlchemyOrderCancellationRepository(db).cancel(
            cancellation_setup().order, uuid4(), NOW, "Order cancelled"
        )
    db.add.assert_not_called()


async def test_pending_request_lock_and_scope_refresh():
    db = session()
    repo = SQLAlchemyCancellationRepository(db)
    await repo.pending_request(uuid4())
    assert "FOR UPDATE" in latest(db) and "cancellation_requests.status =" in latest(db)
    await repo.request(uuid4(), uuid4(), lock=True)
    assert "branch_id =" in latest(db) and "FOR UPDATE" in latest(db)
    assert db.execute.call_args.args[0].get_execution_options()["populate_existing"]


async def test_decision_only_updates_evaluation_not_request_evidence():
    db = session()
    old = request()
    new = decide_request(old, RequestStatus.APPROVED, uuid4(), NOW, "Checked")
    db.execute.return_value.scalar_one_or_none.return_value = CancellationRequestModel(
        **asdict(new)
    )
    assert await SQLAlchemyCancellationRepository(db).save_request(old, new) == new
    statement = latest(db)
    assert "branch_id =" in statement and "status =" in statement
    changes = statement.split(" WHERE ")[0]
    assert "evaluated_at=" in changes and "evaluation_note=" in changes
    for key in ("reason", "requested_at", "order_id", "customer_id", "branch_id"):
        assert key + "=" not in changes
    db.commit.assert_not_awaited()


async def test_lists_are_scoped_sorted_paginated_and_readonly():
    db = session()
    repo = SQLAlchemyCancellationRepository(db)
    await repo.list_owned(uuid4(), uuid4(), 10, 2)
    assert "customer_id =" in latest(db) and "order_id =" in latest(db)
    assert (
        "requested_at DESC" in latest(db)
        and "LIMIT" in latest(db)
        and "OFFSET" in latest(db)
    )
    await repo.list_branch(uuid4(), RequestStatus.PENDING, 10, 2)
    assert (
        "branch_id =" in latest(db)
        and "status =" in latest(db)
        and "FOR UPDATE" not in latest(db)
    )
    db.flush.assert_not_awaited()


async def test_mapper_rejects_corrupt_provenance_without_pii():
    bad = CancellationRequestModel(
        **(asdict(request()) | {"status": "APPROVED", "reason": "PRIVATE_REASON"})
    )
    with pytest.raises(DependencyUnavailableError) as error:
        request_domain(bad)
    assert "PRIVATE" not in str(error.value)


async def test_integrity_error_is_safe_and_transaction_can_rollback():
    db = session()
    db.flush.side_effect = IntegrityError(
        "PRIVATE SQL", {}, RuntimeError("PRIVATE constraint")
    )
    repo = SQLAlchemyCancellationRepository(db)
    with pytest.raises(CancellationConflictError) as error:
        await repo.insert_request(request())
    assert "PRIVATE" not in str(error.value)
    await repo.rollback()
    db.rollback.assert_awaited_once()
