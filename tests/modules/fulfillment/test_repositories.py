from dataclasses import asdict, replace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.fulfillment.application.errors import (
    FulfillmentConflictError,
    FulfillmentDataError,
)
from app.modules.fulfillment.domain.models import DecisionStatus
from app.modules.fulfillment.domain.policies import evaluate_incident
from app.modules.fulfillment.infrastructure.persistence.models import (
    DeliveryAssignmentModel,
    DeliveryDelayIncidentModel,
)
from app.modules.fulfillment.infrastructure.persistence.repositories import (
    SQLAlchemyFulfillmentRepository,
    assignment_domain,
    incident_domain,
)
from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.models import OrderMode, OrderStatus, StatusHistory
from app.modules.orders.infrastructure.fulfillment import (
    SQLAlchemyOrderFulfillmentRepository,
    fulfillment_context,
    fulfillment_query,
)
from app.shared.application.exceptions import DependencyUnavailableError
from tests.modules.fulfillment.fakes import NOW, record
from tests.modules.fulfillment.test_domain import assignment, incident

pytestmark = pytest.mark.anyio


def session():
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    result.mappings.return_value.one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    value = MagicMock()
    value.execute = AsyncMock(return_value=result)
    value.flush = AsyncMock()
    value.commit = AsyncMock()
    value.rollback = AsyncMock()
    return value


def sql(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True}
        )
    )


def latest(db):
    return sql(db.execute.call_args.args[0])


def test_projection_is_batched_historical_minimal_and_orders_owned():
    statement = sql(fulfillment_query())
    assert statement.count("LATERAL") == 1
    assert (
        "order_pickup_details" in statement
        and "order_delivery_details" in statement
        and "order_status_history" in statement
    )
    for forbidden in (
        "customers",
        "customer_addresses",
        "products",
        "payments",
        "orders.total",
        "orders.idempotency_key",
        "password_hash",
        "orders.customer_id",
    ):
        assert forbidden not in statement
    assert "delivered_history_count" in statement


async def test_pickup_batch_is_scoped_due_paid_and_skip_locked():
    db = session()
    await SQLAlchemyOrderFulfillmentRepository(db).pickup_candidates(
        uuid4(), 10, now=NOW, prep_minutes=25, lock=True
    )
    statement = latest(db)
    assert "FOR UPDATE OF orders SKIP LOCKED" in statement
    for text in (
        "orders.branch_id =",
        "orders.mode =",
        "orders.status =",
        "orders.payment_status =",
        "orders.payment_method_type =",
        "orders.confirmed_at IS NOT NULL",
        "order_pickup_details.requested_pickup_at <=",
        "LIMIT",
    ):
        assert text in statement
    assert "calculated_kitchen_release_at <=" not in statement
    db.commit.assert_not_awaited()


async def test_due_get_and_delivery_queue_do_not_lock_or_write():
    db = session()
    repo = SQLAlchemyOrderFulfillmentRepository(db)
    await repo.pickup_candidates(uuid4(), 20, 5)
    assert "FOR UPDATE" not in latest(db) and "OFFSET" in latest(db)
    await repo.delivery_queue(uuid4(), OrderStatus.READY, 20, 5)
    assert "FOR UPDATE" not in latest(db) and "orders.branch_id =" in latest(db)
    assert db.execute.await_count == 2
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_lock_order_uses_only_order_lock_and_branch_filter():
    db = session()
    assert (
        await SQLAlchemyOrderFulfillmentRepository(db).lock_order(uuid4(), uuid4())
        is None
    )
    assert "FOR UPDATE OF orders" in latest(db)
    assert "orders.branch_id =" in latest(db) and "orders.id =" in latest(db)
    assert "FOR UPDATE OF order_delivery" not in latest(db)


async def test_delay_scan_actual_history_strict_deadline_cursor_and_skip_locked():
    db = session()
    await SQLAlchemyOrderFulfillmentRepository(db).delay_candidates(
        uuid4(), NOW, 5, 123
    )
    statement = latest(db)
    assert statement.count("LATERAL") == 1
    assert "fulfillment_history.delivered_at >" in statement
    assert "fulfillment_history.delivered_history_count !=" in statement
    assert "orders.order_number >" in statement
    assert "FOR UPDATE OF orders SKIP LOCKED" in statement
    assert "order_delivery_details.estimated_delivery_at +" in statement
    assert "<" in statement and ">=" not in statement.split("WHERE orders.branch_id")[1]


async def test_transition_updates_only_status_and_history_without_adapter_commit():
    db = session()
    order = record(uuid4())
    db.execute.return_value.scalar_one_or_none.return_value = order.id
    await SQLAlchemyOrderFulfillmentRepository(db).record_fulfillment_transition(
        order,
        StatusHistory(
            from_status=order.status,
            to_status=OrderStatus.WAITING,
            changed_by_user_id=uuid4(),
            created_at=NOW,
        ),
    )
    statement = latest(db)
    assert statement.startswith("UPDATE orders SET status=")
    assert "orders.status =" in statement and "orders.branch_id =" in statement
    assert (
        "payment_status=" not in statement.split(" WHERE ")[0]
        and "total" not in statement
    )
    history = db.add.call_args.args[0]
    assert history.to_status == OrderStatus.WAITING and history.order_id == order.id
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_lost_conditional_transition_no_history_written():
    db = session()
    order = record(uuid4())
    with pytest.raises(OrderConflictError):
        await SQLAlchemyOrderFulfillmentRepository(db).record_fulfillment_transition(
            order,
            StatusHistory(
                from_status=order.status,
                to_status=OrderStatus.WAITING,
                changed_by_user_id=uuid4(),
                created_at=NOW,
            ),
        )
    db.add.assert_not_called()


def test_corrupt_delivered_projection_safe_error_without_pii():
    order = record(uuid4(), OrderMode.DELIVERY, OrderStatus.DELIVERED)
    row = asdict(order) | {
        "delivered_history_count": 0,
        "address_line_snapshot": "PRIVATE_ADDRESS",
    }
    with pytest.raises(DependencyUnavailableError) as error:
        fulfillment_context(row)
    assert "PRIVATE_ADDRESS" not in str(error.value)


async def test_active_assignments_batch_no_n_plus_one():
    db = session()
    repo = SQLAlchemyFulfillmentRepository(db)
    assert await repo.active_assignments([]) == {}
    db.execute.assert_not_awaited()
    value = assignment()
    db.execute.return_value.scalars.return_value.all.return_value = [
        DeliveryAssignmentModel(**asdict(value))
    ]
    rows = await repo.active_assignments([value.order_id, uuid4()])
    assert rows[value.order_id] == value and db.execute.await_count == 1
    assert (
        "order_id IN" in latest(db)
        and "unassigned_at IS NULL" in latest(db)
        and "completed_at IS NULL" in latest(db)
    )


async def test_assignment_lock_and_close_touch_terminal_fields_only():
    db = session()
    repo = SQLAlchemyFulfillmentRepository(db)
    await repo.active_assignment(uuid4(), lock=True)
    assert "FOR UPDATE" in latest(db)
    original = assignment()
    updated = replace(original, completed_at=NOW)
    db.execute.return_value.scalar_one_or_none.return_value = DeliveryAssignmentModel(
        **asdict(updated)
    )
    assert await repo.close_assignment(original, updated) == updated
    statement = latest(db)
    assert "completed_at=" in statement.split(" WHERE ")[0]
    assert "assigned_user_id=" not in statement.split(" WHERE ")[0]
    assert "unassigned_at IS NULL" in statement and "completed_at IS NULL" in statement
    db.commit.assert_not_awaited()


async def test_incident_insert_conflict_does_not_overwrite_evidence():
    db = session()
    repo = SQLAlchemyFulfillmentRepository(db)
    assert not await repo.insert_incident(incident())
    statement = latest(db)
    assert (
        "ON CONFLICT ON CONSTRAINT uq_delivery_delay_incidents_order DO NOTHING"
        in statement
    )
    assert "DO UPDATE" not in statement
    db.commit.assert_not_awaited()


async def test_incident_list_and_lock_scoped_and_stable_sort():
    db = session()
    repo = SQLAlchemyFulfillmentRepository(db)
    await repo.list_incidents(uuid4(), DecisionStatus.OPEN, 10, 20)
    statement = latest(db)
    assert "branch_id =" in statement and "decision_status =" in statement
    assert "detected_at DESC, delivery_delay_incidents.id DESC" in statement
    assert "FOR UPDATE" not in statement
    await repo.lock_incident(uuid4(), uuid4())
    assert (
        "branch_id =" in latest(db)
        and "id =" in latest(db)
        and "FOR UPDATE" in latest(db)
    )
    assert "orders" not in latest(db)


async def test_decision_update_does_not_modify_detection_evidence():
    db = session()
    original = incident()
    decided = evaluate_incident(
        original, DecisionStatus.REJECTED, uuid4(), NOW, False, "note", None
    )
    db.execute.return_value.scalar_one_or_none.return_value = (
        DeliveryDelayIncidentModel(**asdict(decided))
    )
    result = await SQLAlchemyFulfillmentRepository(db).save_decision(original, decided)
    assert result == decided
    changes = latest(db).split(" WHERE ")[0]
    for field in (
        "committed_eta",
        "detected_at",
        "observed_order_status",
        "delay_seconds_at_detection",
        "order_id",
        "branch_id",
    ):
        assert field + "=" not in changes
    assert "decision_status =" in latest(db).split(" WHERE ")[1]


async def test_staff_eligibility_branch_active_full_membership_and_share_lock():
    db = session()
    assert not await SQLAlchemyBranchRepository(db).staff_is_active(
        uuid4(), uuid4(), NOW
    )
    statement = latest(db)
    for text in (
        "staff_assignments.branch_id =",
        "staff_assignments.user_id =",
        "staff_assignments.is_active IS true",
        "staff_assignments.ended_at IS NULL",
        "staff_assignments.assigned_at <=",
        "users.account_status =",
        "users.deleted_at IS NULL",
        "branches.is_active IS true",
        "branches.deleted_at IS NULL",
        "roles.scope =",
        "FOR SHARE OF staff_assignments, users",
    ):
        assert text in statement


@pytest.mark.parametrize(
    "operation", ["commit", "insert_assignment", "insert_incident"]
)
async def test_integrity_errors_are_safe_and_application_can_rollback(operation):
    db = session()
    failure = IntegrityError("PRIVATE SQL", {}, RuntimeError("PRIVATE constraint"))
    if operation == "commit":
        db.commit.side_effect = failure
    elif operation == "insert_assignment":
        db.flush.side_effect = failure
    else:
        db.execute.side_effect = failure
    repo = SQLAlchemyFulfillmentRepository(db)
    with pytest.raises(FulfillmentConflictError) as error:
        await getattr(repo, operation)(
            *(
                ()
                if operation == "commit"
                else (assignment() if operation == "insert_assignment" else incident(),)
            )
        )
    assert "PRIVATE" not in str(error.value)
    await repo.rollback()
    db.rollback.assert_awaited_once()


def test_corrupt_mapper_safe_without_evidence_leak():
    bad_assignment = DeliveryAssignmentModel(
        **(asdict(assignment()) | {"unassigned_at": NOW})
    )
    bad_incident = DeliveryDelayIncidentModel(
        **(asdict(incident()) | {"decision_status": "INVALID"})
    )
    for mapper, value in [
        (assignment_domain, bad_assignment),
        (incident_domain, bad_incident),
    ]:
        with pytest.raises(FulfillmentDataError):
            mapper(value)
