import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.fulfillment.application.errors import (
    FulfillmentConflictError,
    FulfillmentNotFoundError,
    FulfillmentPermissionDeniedError,
)
from app.modules.fulfillment.application.services import FulfillmentService
from app.modules.fulfillment.domain.models import DecisionStatus
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
)
from app.shared.application.exceptions import RequestDataError
from tests.modules.fulfillment.fakes import (
    MemoryAudit,
    MemoryOrders,
    MemoryRepository,
    change_order,
    delivery_order,
    record,
)

pytestmark = pytest.mark.anyio


def args(setup):
    return setup.admin, setup.branch, setup.order.id


async def test_due_read_only_and_recomputed_without_mutating_initial_snapshots(setup):
    original = setup.order
    rows = await setup.service.pickup_due(setup.admin, setup.branch)
    assert rows[0].is_due
    assert rows[0].recommended_release_at == original.calculated_kitchen_release_at
    waiting = record(setup.branch, OrderMode.LOCAL, OrderStatus.WAITING, number=2)
    setup.store.orders[waiting.id] = waiting
    setup.store.settings[setup.branch] = replace(
        setup.store.settings[setup.branch], default_prep_minutes=30
    )
    row = (await setup.service.pickup_due(setup.admin, setup.branch))[0]
    assert row.queue_depth == 1
    assert (
        row.recommended_release_at
        == original.calculated_kitchen_release_at - timedelta(minutes=15)
    )
    assert row.initial_release_at == original.calculated_kitchen_release_at
    assert row.initial_estimated_ready_at == original.estimated_ready_at
    assert setup.store.orders[original.id] == original
    assert (
        not setup.store.histories
        and not setup.store.incidents
        and setup.repo.commits == 0
    )


async def test_release_due_boundary_history_actor_and_idempotency(setup):
    original = setup.order
    result = await setup.service.release_pickup(*args(setup))
    assert result.status == OrderStatus.WAITING and result.changed
    changed = setup.store.orders[original.id]
    assert changed.requested_pickup_at == original.requested_pickup_at
    assert (
        changed.calculated_kitchen_release_at == original.calculated_kitchen_release_at
    )
    assert changed.estimated_ready_at == original.estimated_ready_at
    history = setup.store.histories[0][1]
    assert (
        history.changed_by_user_id == setup.admin.user_id
        and history.created_at == setup.now
    )
    assert history.from_status == OrderStatus.SCHEDULED
    assert "released" in history.reason
    assert not (await setup.service.release_pickup(*args(setup))).changed
    assert len(setup.store.histories) == 1


async def test_early_pickup_not_released(setup):
    setup.now -= timedelta(microseconds=1)
    with pytest.raises(FulfillmentConflictError) as error:
        await setup.service.release_pickup(*args(setup))
    assert error.value.code == "PICKUP_NOT_DUE"
    assert setup.store.orders[setup.order.id] == setup.order
    assert not setup.store.histories


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PREPARING,
        OrderStatus.READY_FOR_PICKUP,
        OrderStatus.PICKED_UP,
        OrderStatus.CANCELLED,
    ],
)
async def test_release_cannot_skip_or_reverse_statuses(setup, status):
    change_order(setup, status=status)
    with pytest.raises(FulfillmentConflictError):
        await setup.service.release_pickup(*args(setup))


async def test_bulk_releases_five_due_not_five_future_with_one_queue_snapshot(setup):
    setup.store.orders.clear()
    for number in range(1, 11):
        order = record(
            setup.branch,
            number=number,
            requested_pickup_at=setup.now
            + timedelta(minutes=25 if number <= 5 else 90),
        )
        setup.store.orders[order.id] = order
    result = await setup.service.release_due_pickups(setup.admin, setup.branch, 10)
    assert result.evaluated == result.released == 5 and result.queue_depth == 0
    assert (
        sum(o.status == OrderStatus.SCHEDULED for o in setup.store.orders.values()) == 5
    )
    assert len(setup.store.histories) == 5
    again = await setup.service.release_due_pickups(setup.admin, setup.branch, 10)
    assert again.released == 0 and len(setup.store.histories) == 5


async def test_bulk_limit_and_branch_payment_isolation(setup):
    for number, changes in enumerate(
        [
            {},
            {},
            {"branch_id": uuid4()},
            {"payment_status": PaymentStatus.PENDING},
            {"confirmed_at": None},
            {"payment_method_type": PaymentMethodType.CASH},
        ],
        2,
    ):
        order = record(setup.branch, number=number, **changes)
        setup.store.orders[order.id] = order
    result = await setup.service.release_due_pickups(setup.admin, setup.branch, 2)
    assert result.released == 2
    assert len(setup.store.histories) == 2
    assert all(
        setup.store.orders[o.order_id].branch_id == setup.branch for o in result.orders
    )


async def test_pickup_requires_full_snapshot_identity_and_does_not_persist_input(setup):
    change_order(setup, status=OrderStatus.READY_FOR_PICKUP)
    for name, phone in [
        ("María", "+51999888777"),
        ("María López", "999888777"),
        ("Wrong", "+51999888777"),
    ]:
        with pytest.raises(FulfillmentConflictError) as error:
            await setup.service.complete_pickup(*args(setup), name, phone)
        assert error.value.code == "PICKUP_IDENTITY_MISMATCH"
    result = await setup.service.complete_pickup(
        *args(setup), " MARÍA   LÓPEZ ", "+51 (999) 888-777"
    )
    assert result.status == OrderStatus.PICKED_UP and result.changed
    assert not (
        await setup.service.complete_pickup(*args(setup), "María López", "51999888777")
    ).changed
    assert len(setup.store.histories) == 1
    assert "María" not in repr(setup.store.histories) and "888" not in repr(
        setup.store.histories
    )
    with pytest.raises(FulfillmentConflictError):
        await setup.service.complete_pickup(*args(setup), "Wrong", "51999888777")


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.SCHEDULED,
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.CANCELLED,
    ],
)
async def test_pickup_handover_cannot_skip_kitchen(setup, status):
    change_order(setup, status=status)
    with pytest.raises(FulfillmentConflictError):
        await setup.service.complete_pickup(*args(setup), "María López", "+51999888777")


@pytest.mark.parametrize(
    "changes",
    [
        {"payment_status": PaymentStatus.PENDING},
        {"payment_method_type": PaymentMethodType.CASH},
        {"confirmed_at": None},
    ],
)
async def test_all_pickup_commands_require_confirmed_paid_online(setup, changes):
    change_order(setup, **changes)
    with pytest.raises(FulfillmentConflictError):
        await setup.service.release_pickup(*args(setup))
    assert not await setup.service.pickup_due(setup.admin, setup.branch)
    assert (
        await setup.service.release_due_pickups(setup.admin, setup.branch)
    ).released == 0


@pytest.mark.parametrize("who", ["guest", "customer", "kitchen", "foreign"])
@pytest.mark.parametrize(
    "method",
    [
        "pickup_due",
        "release_due_pickups",
        "delivery_queue",
        "detect_delivery_delays",
        "list_delays",
    ],
)
async def test_permissions_not_inferred_from_jwt_identity_or_kitchen(
    setup, who, method
):
    with pytest.raises(FulfillmentPermissionDeniedError):
        await getattr(setup.service, method)(getattr(setup, who), setup.branch)


async def test_branch_scope_hides_other_branch_order_and_incident(setup):
    foreign_branch = uuid4()
    setup.store.grants.add((setup.admin.user_id, foreign_branch, "FULFILLMENT_MANAGE"))
    with pytest.raises(FulfillmentNotFoundError):
        await setup.service.release_pickup(setup.admin, foreign_branch, setup.order.id)
    delivery_order(setup)
    await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    incident = next(iter(setup.store.incidents.values()))
    setup.store.grants.add(
        (setup.admin.user_id, foreign_branch, "DELIVERY_DELAY_REVIEW")
    )
    with pytest.raises(FulfillmentNotFoundError):
        await setup.service.decide_delay(
            setup.admin, foreign_branch, incident.id, DecisionStatus.REJECTED
        )


async def test_delivery_queue_snapshots_filter_pagination_and_no_writes(setup):
    order = delivery_order(setup)
    for number, status in enumerate(
        [
            OrderStatus.WAITING,
            OrderStatus.PREPARING,
            OrderStatus.OUT_FOR_DELIVERY,
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
        ],
        2,
    ):
        item = record(setup.branch, OrderMode.DELIVERY, status, number)
        setup.store.orders[item.id] = item
    rows = await setup.service.delivery_queue(setup.admin, setup.branch)
    assert len(rows) == 4
    assert rows[0].order.address_line_snapshot == order.address_line_snapshot
    assert rows[0].is_delayed and rows[0].current_delay_seconds == 1200
    filtered = await setup.service.delivery_queue(
        setup.admin, setup.branch, OrderStatus.PREPARING
    )
    assert len(filtered) == 1
    assert (
        len(
            await setup.service.delivery_queue(
                setup.admin, setup.branch, limit=1, offset=2
            )
        )
        == 1
    )
    assert not setup.store.incidents and setup.repo.commits == 0


async def test_assignment_reassignment_unassignment_history_and_audit(setup):
    original = delivery_order(setup)
    first = await setup.service.assign_delivery(*args(setup), setup.kitchen.user_id)
    assert (
        await setup.service.assign_delivery(*args(setup), setup.kitchen.user_id)
    ).id == first.id
    assert len(setup.store.assignments) == len(setup.store.audits) == 1
    setup.now += timedelta(seconds=1)
    second = await setup.service.assign_delivery(*args(setup), setup.admin.user_id)
    closed = setup.store.assignments[first.id]
    assert (
        closed.unassigned_at == setup.now
        and closed.unassigned_by_user_id == setup.admin.user_id
    )
    assert second.active and second.id != first.id
    assert setup.store.orders[original.id] == original
    assert [a.action for a in setup.store.audits] == [
        "DELIVERY_ASSIGNED",
        "DELIVERY_REASSIGNED",
    ]
    await setup.service.unassign_delivery(*args(setup))
    await setup.service.unassign_delivery(*args(setup))
    assert len(setup.store.assignments) == 2 and not any(
        a.active for a in setup.store.assignments.values()
    )
    assert len(setup.store.audits) == 3
    assert setup.store.trace[:2] == ["order", "assignment"]


async def test_unknown_or_inactive_or_other_branch_assignee_rejected(setup):
    delivery_order(setup)
    other = uuid4()
    setup.store.staff.add((other, uuid4()))
    for user in (other, uuid4(), setup.customer.user_id):
        with pytest.raises(FulfillmentConflictError) as error:
            await setup.service.assign_delivery(*args(setup), user)
        assert error.value.code == "DELIVERY_ASSIGNEE_INVALID"
    assert not setup.store.assignments


async def test_dispatch_and_completion_atomic_history_and_assignment(setup):
    original = delivery_order(setup)
    with pytest.raises(FulfillmentConflictError) as error:
        await setup.service.dispatch_delivery(*args(setup))
    assert error.value.code == "DELIVERY_ASSIGNMENT_REQUIRED"
    assignment = await setup.service.assign_delivery(
        *args(setup), setup.kitchen.user_id
    )
    assert (await setup.service.dispatch_delivery(*args(setup))).changed
    assert not (await setup.service.dispatch_delivery(*args(setup))).changed
    setup.now += timedelta(minutes=10)
    assert (await setup.service.complete_delivery(*args(setup))).changed
    assert not (await setup.service.complete_delivery(*args(setup))).changed
    assert setup.store.assignments[assignment.id].completed_at == setup.now
    assert (
        setup.store.orders[original.id].estimated_delivery_at
        == original.estimated_delivery_at
    )
    assert [h.to_status for _, h in setup.store.histories] == [
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
    ]
    assert all(
        h.changed_by_user_id == setup.admin.user_id for _, h in setup.store.histories
    )


async def test_assignee_revocation_blocks_dispatch_but_does_not_rewrite_assignment(
    setup,
):
    delivery_order(setup)
    assignment = await setup.service.assign_delivery(
        *args(setup), setup.kitchen.user_id
    )
    setup.store.staff.remove((setup.kitchen.user_id, setup.branch))
    with pytest.raises(FulfillmentConflictError):
        await setup.service.dispatch_delivery(*args(setup))
    assert setup.store.assignments[assignment.id] == assignment


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.CANCELLED,
        OrderStatus.DELIVERED,
    ],
)
async def test_dispatch_only_from_ready(setup, status):
    delivery_order(setup, status)
    with pytest.raises(FulfillmentConflictError):
        await setup.service.dispatch_delivery(*args(setup))


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.CANCELLED,
    ],
)
async def test_complete_only_from_dispatched(setup, status):
    delivery_order(setup, status)
    with pytest.raises(FulfillmentConflictError):
        await setup.service.complete_delivery(*args(setup))


@pytest.mark.parametrize(
    "status",
    [OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED, OrderStatus.CANCELLED],
)
async def test_assignment_changes_forbidden_after_dispatch(setup, status):
    delivery_order(setup, status)
    for method, extra in [
        ("assign_delivery", (setup.kitchen.user_id,)),
        ("unassign_delivery", ()),
    ]:
        with pytest.raises(FulfillmentConflictError):
            await getattr(setup.service, method)(*args(setup), *extra)


@pytest.mark.parametrize(
    "changes",
    [
        {"payment_status": PaymentStatus.PENDING},
        {"confirmed_at": None},
        {"payment_method_type": PaymentMethodType.CASH},
    ],
)
async def test_delivery_paid_gate_applies_to_queue_assignment_dispatch_and_complete(
    setup, changes
):
    delivery_order(setup, **changes)
    assert not await setup.service.delivery_queue(setup.admin, setup.branch)
    assert (
        await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    ).evaluated == 0
    for method, extra in [
        ("assign_delivery", (setup.kitchen.user_id,)),
        ("dispatch_delivery", ()),
        ("complete_delivery", ()),
    ]:
        with pytest.raises(FulfillmentConflictError):
            await getattr(setup.service, method)(*args(setup), *extra)


async def test_delay_detection_readonly_list_then_idempotent_immutable_evidence(setup):
    order = delivery_order(setup)
    assert not await setup.service.list_delays(setup.admin, setup.branch)
    result = await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    assert result.new_incidents == 1 and result.existing_incidents == 0
    incident = next(iter(setup.store.incidents.values()))
    assert (
        incident.order_id == order.id
        and incident.committed_eta == order.estimated_delivery_at
    )
    assert incident.decision_status == DecisionStatus.OPEN
    setup.now += timedelta(hours=1)
    repeated = await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    assert repeated.new_incidents == 0 and repeated.existing_incidents == 1
    assert next(iter(setup.store.incidents.values())) == incident
    assert not setup.store.histories and not setup.store.audits


async def test_delay_cursor_does_not_starve_later_orders(setup):
    setup.store.orders.clear()
    for number in range(1, 8):
        order = record(setup.branch, OrderMode.DELIVERY, number=number)
        setup.store.orders[order.id] = order
    first = await setup.service.detect_delivery_delays(
        setup.admin, setup.branch, limit=3
    )
    second = await setup.service.detect_delivery_delays(
        setup.admin, setup.branch, limit=3, after_order_number=first.next_order_number
    )
    third = await setup.service.detect_delivery_delays(
        setup.admin, setup.branch, limit=3, after_order_number=second.next_order_number
    )
    assert (
        first.next_order_number,
        second.next_order_number,
        third.next_order_number,
    ) == (3, 6, None)
    assert len(setup.store.incidents) == 7


async def test_delivered_delay_uses_actual_history_not_later_query_time(setup):
    delivery_order(
        setup,
        OrderStatus.DELIVERED,
        estimated_delivery_at=setup.now - timedelta(minutes=10),
    )
    setup.now += timedelta(days=10)
    assert (
        await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    ).new_incidents == 0


@pytest.mark.parametrize("target", [DecisionStatus.APPROVED, DecisionStatus.REJECTED])
@pytest.mark.parametrize("responsibility", [None, False, True])
async def test_decision_requires_human_action_preserves_evidence_and_is_idempotent(
    setup, target, responsibility
):
    original_order = delivery_order(setup)
    await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    incident = next(iter(setup.store.incidents.values()))
    description = (
        "Manual service follow-up" if target == DecisionStatus.APPROVED else None
    )
    decided = await setup.service.decide_delay(
        setup.admin,
        setup.branch,
        incident.id,
        target,
        responsibility,
        "Verified manually",
        description,
    )
    again = await setup.service.decide_delay(
        setup.admin,
        setup.branch,
        incident.id,
        target,
        responsibility,
        "Verified manually",
        description,
    )
    assert again == decided and decided.customer_responsibility is responsibility
    assert decided.evaluated_by_user_id == setup.admin.user_id
    assert (
        decided.detected_at == incident.detected_at
        and decided.committed_eta == incident.committed_eta
    )
    assert setup.store.orders[original_order.id] == original_order
    assert not setup.store.histories and len(setup.store.audits) == 1
    opposite = (
        DecisionStatus.REJECTED
        if target == DecisionStatus.APPROVED
        else DecisionStatus.APPROVED
    )
    with pytest.raises(FulfillmentConflictError):
        await setup.service.decide_delay(
            setup.admin,
            setup.branch,
            incident.id,
            opposite,
            remediation="Other" if opposite == DecisionStatus.APPROVED else None,
        )


@pytest.mark.parametrize("failure", ["fail_history", "fail_commit"])
async def test_status_history_and_commit_failure_rollback(setup, failure):
    setattr(setup.repo, failure, True)
    with pytest.raises(RuntimeError):
        await setup.service.release_pickup(*args(setup))
    assert (
        setup.store.orders[setup.order.id] == setup.order and not setup.store.histories
    )
    assert setup.repo.rollbacks == 1 and not setup.store.lock.locked()


async def test_assignment_close_failure_rolls_back_delivered_status_history(setup):
    delivery_order(setup)
    assignment = await setup.service.assign_delivery(
        *args(setup), setup.kitchen.user_id
    )
    await setup.service.dispatch_delivery(*args(setup))
    original = setup.store.orders[setup.order.id]
    histories = list(setup.store.histories)
    setup.repo.fail_completion = True
    with pytest.raises(RuntimeError):
        await setup.service.complete_delivery(*args(setup))
    assert setup.store.orders[original.id] == original
    assert (
        setup.store.assignments[assignment.id] == assignment
        and setup.store.histories == histories
    )


async def test_audit_failure_rolls_back_assignment_and_decision(setup):
    delivery_order(setup)
    setup.repo.fail_audit = True
    with pytest.raises(RuntimeError):
        await setup.service.assign_delivery(*args(setup), setup.kitchen.user_id)
    assert not setup.store.assignments
    setup.repo.fail_audit = False
    await setup.service.detect_delivery_delays(setup.admin, setup.branch)
    incident = next(iter(setup.store.incidents.values()))
    setup.repo.fail_audit = True
    with pytest.raises(RuntimeError):
        await setup.service.decide_delay(
            setup.admin, setup.branch, incident.id, DecisionStatus.REJECTED
        )
    assert setup.store.incidents[incident.id] == incident


def concurrent_service(setup):
    repo = MemoryRepository(setup.store)
    return FulfillmentService(
        repo,
        MemoryOrders(repo),
        setup.authorization,
        MemoryAudit(repo),
        clock=lambda: setup.now,
    )


async def test_simultaneous_pickup_release_no_duplicate_history(setup):
    results = await asyncio.gather(
        *(concurrent_service(setup).release_pickup(*args(setup)) for _ in range(4))
    )
    assert sum(r.changed for r in results) == 1 and len(setup.store.histories) == 1


async def test_simultaneous_handover_no_duplicate_history(setup):
    change_order(setup, status=OrderStatus.READY_FOR_PICKUP)
    results = await asyncio.gather(
        *(
            concurrent_service(setup).complete_pickup(
                *args(setup), "María López", "+51999888777"
            )
            for _ in range(4)
        )
    )
    assert sum(r.changed for r in results) == 1 and len(setup.store.histories) == 1


async def test_simultaneous_assignment_no_duplicate_active_row(setup):
    delivery_order(setup)
    results = await asyncio.gather(
        *(
            concurrent_service(setup).assign_delivery(
                *args(setup), setup.kitchen.user_id
            )
            for _ in range(4)
        )
    )
    assert len({r.id for r in results}) == len(setup.store.assignments) == 1


async def test_simultaneous_dispatch_completion_and_detection(setup):
    delivery_order(setup)
    await setup.service.assign_delivery(*args(setup), setup.kitchen.user_id)
    dispatch = await asyncio.gather(
        *(concurrent_service(setup).dispatch_delivery(*args(setup)) for _ in range(3))
    )
    complete = await asyncio.gather(
        *(concurrent_service(setup).complete_delivery(*args(setup)) for _ in range(3))
    )
    detection = await asyncio.gather(
        *(
            concurrent_service(setup).detect_delivery_delays(setup.admin, setup.branch)
            for _ in range(3)
        )
    )
    assert sum(r.changed for r in dispatch) == sum(r.changed for r in complete) == 1
    assert sum(r.new_incidents for r in detection) == 1
    assert len(setup.store.histories) == 2 and len(setup.store.incidents) == 1


@pytest.mark.parametrize(
    "limit,offset", [(0, 0), (101, 0), (True, 0), (1, -1), (1, 2147483648)]
)
async def test_service_pagination_bounded(setup, limit, offset):
    with pytest.raises(RequestDataError):
        await setup.service.pickup_due(setup.admin, setup.branch, limit, offset)


@pytest.mark.parametrize("cursor", [-1, True, 9223372036854775808, "1"])
async def test_scan_cursor_bounded(setup, cursor):
    with pytest.raises(RequestDataError):
        await setup.service.detect_delivery_delays(
            setup.admin, setup.branch, after_order_number=cursor
        )
