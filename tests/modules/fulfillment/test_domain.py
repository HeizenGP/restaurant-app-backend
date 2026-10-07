from dataclasses import replace
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from app.modules.fulfillment.domain.models import (
    MAX_SECONDS,
    DecisionStatus,
    DeliveryAssignment,
    DeliveryDelayIncident,
    FulfillmentRuleError,
)
from app.modules.fulfillment.domain.policies import (
    delay_seconds,
    evaluate_incident,
    identity_matches,
    is_delayed,
    normalized_name,
    normalized_phone,
    recommended_release,
)
from app.modules.orders.domain.fulfillment import validate_fulfillment_transition
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)
from tests.modules.fulfillment.fakes import NOW, record


@pytest.mark.parametrize("depth", [0, 1, 5, 10, 100])
def test_release_uses_current_settings_and_queue(depth):
    settings = BranchOrderSettings(branch_id=uuid4())
    requested = NOW + timedelta(minutes=60)
    release, ready = recommended_release(requested, settings, depth)
    assert ready == requested - timedelta(minutes=settings.pickup_buffer_minutes)
    assert release == ready - timedelta(
        minutes=settings.default_prep_minutes
        + depth * settings.queue_delay_per_order_minutes
    )


@pytest.mark.parametrize("depth", [-1, True, 1.5, "1", None])
def test_invalid_queue_depth(depth):
    with pytest.raises(FulfillmentRuleError):
        recommended_release(NOW, BranchOrderSettings(branch_id=uuid4()), depth)


def test_naive_and_overflow_release_rejected():
    settings = BranchOrderSettings(branch_id=uuid4())
    for date, depth in [(NOW.replace(tzinfo=None), 0), (NOW, 10**30)]:
        with pytest.raises(FulfillmentRuleError):
            recommended_release(date, settings, depth)


@pytest.mark.parametrize("name", ["María López", " MARÍA   LÓPEZ ", "maría lópez"])
@pytest.mark.parametrize("phone", ["+51999888777", "51999888777", "+51 (999) 888-777"])
def test_complete_snapshot_identity_matches(name, phone):
    assert identity_matches(name, phone, "María López", "+51999888777")


@pytest.mark.parametrize(
    "name,phone",
    [
        ("Maria Lopez", "+51999888777"),
        ("María", "+51999888777"),
        ("María López", "999888777"),
        ("María López", "+51999888778"),
    ],
)
def test_identity_is_not_fuzzy_or_suffix_only(name, phone):
    assert not identity_matches(name, phone, "María López", "+51999888777")


@pytest.mark.parametrize(
    "phone",
    [
        "777",
        "",
        "++51999888777",
        "1234567890123456",
        "＋51999888777",
        "+٥١٩٩٩٨٨٨٧٧٧",
        "+51999888777\n",
        "51/999888777",
        "phone51999888777",
    ],
)
def test_invalid_full_phone(phone):
    with pytest.raises(FulfillmentRuleError):
        normalized_phone(phone)


@pytest.mark.parametrize(
    "name", ["", " ", "x" * 181, "María\x00López", "María\nLópez", "María\u200bLópez"]
)
def test_invalid_name(name):
    with pytest.raises(FulfillmentRuleError):
        normalized_name(name)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (-1, False),
        (0, False),
        (899, False),
        (900, False),
        (900.000001, True),
        (901, True),
    ],
)
@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.WAITING,
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
    ],
)
def test_strict_delay_threshold_and_actual_completion(seconds, expected, status):
    eta = NOW - timedelta(seconds=seconds)
    order = record(uuid4(), OrderMode.DELIVERY, status, estimated_delivery_at=eta)
    assert is_delayed(order, NOW) is expected
    if status == OrderStatus.DELIVERED:
        assert is_delayed(order, NOW + timedelta(days=100)) is expected
        assert delay_seconds(order, NOW + timedelta(days=100)) == delay_seconds(
            order, NOW
        )


def test_delay_rounding_timezone_and_saturation():
    order = record(
        uuid4(),
        OrderMode.DELIVERY,
        estimated_delivery_at=NOW - timedelta(seconds=900, microseconds=1),
    )
    assert delay_seconds(order, NOW) == 901
    assert is_delayed(order, NOW.astimezone(timezone(timedelta(hours=-5))))
    assert delay_seconds(order, NOW + timedelta(days=100000)) == MAX_SECONDS


@pytest.mark.parametrize(
    "mode,status",
    [
        (OrderMode.PICKUP, OrderStatus.READY_FOR_PICKUP),
        (OrderMode.LOCAL, OrderStatus.READY),
        (OrderMode.DELIVERY, OrderStatus.CANCELLED),
    ],
)
def test_non_delivery_or_cancelled_has_no_delay(mode, status):
    order = record(uuid4(), mode, status)
    assert not is_delayed(order, NOW)
    assert delay_seconds(order, NOW) == 0


def assignment():
    return DeliveryAssignment(
        order_id=uuid4(),
        assigned_user_id=uuid4(),
        assigned_by_user_id=uuid4(),
        assigned_at=NOW,
        created_at=NOW,
    )


def incident():
    return DeliveryDelayIncident(
        order_id=uuid4(),
        branch_id=uuid4(),
        committed_eta=NOW - timedelta(minutes=20),
        observed_order_status=OrderStatus.READY,
        delay_seconds_at_detection=1200,
        detected_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"unassigned_at": NOW},
        {"unassigned_by_user_id": uuid4()},
        {"completed_at": NOW - timedelta(seconds=1)},
        {"unassigned_at": NOW - timedelta(seconds=1), "unassigned_by_user_id": uuid4()},
        {"completed_at": NOW, "unassigned_at": NOW, "unassigned_by_user_id": uuid4()},
        {"assigned_at": NOW.replace(tzinfo=None)},
        {"reason": " "},
        {"reason": "x" * 201},
    ],
)
def test_assignment_history_invariants(changes):
    with pytest.raises(FulfillmentRuleError):
        replace(assignment(), **changes)


def test_assignment_terminal_states_preserve_history():
    original = assignment()
    assert original.active
    assert not replace(original, completed_at=NOW).active
    assert not replace(
        original, unassigned_at=NOW, unassigned_by_user_id=uuid4()
    ).active
    assert original.active


@pytest.mark.parametrize(
    "changes",
    [
        {"delay_threshold_seconds": 899},
        {"delay_seconds_at_detection": 900},
        {"delay_seconds_at_detection": True},
        {"delay_seconds_at_detection": MAX_SECONDS + 1},
        {"observed_order_status": OrderStatus.CANCELLED},
        {"observed_order_status": "READY"},
        {"decision_status": "OPEN"},
        {"customer_responsibility": False},
        {"evaluated_at": NOW},
        {"evaluation_note": "text"},
        {"committed_eta": NOW.replace(tzinfo=None)},
    ],
)
def test_incident_evidence_invariants(changes):
    with pytest.raises(FulfillmentRuleError):
        replace(incident(), **changes)


@pytest.mark.parametrize("target", [DecisionStatus.APPROVED, DecisionStatus.REJECTED])
@pytest.mark.parametrize("responsibility", [None, False, True])
def test_human_decision_immutable_evidence_and_identical_retry(target, responsibility):
    original = incident()
    actor = uuid4()
    description = " Manual follow-up " if target == DecisionStatus.APPROVED else None
    updated = evaluate_incident(
        original, target, actor, NOW, responsibility, " note ", description
    )
    assert updated.customer_responsibility is responsibility
    assert updated.evaluation_note == "note"
    for name in (
        "id",
        "order_id",
        "branch_id",
        "committed_eta",
        "detected_at",
        "observed_order_status",
        "delay_seconds_at_detection",
        "created_at",
    ):
        assert getattr(updated, name) == getattr(original, name)
    assert (
        evaluate_incident(
            updated,
            target,
            actor,
            NOW + timedelta(hours=1),
            responsibility,
            "note",
            description,
        )
        is updated
    )
    with pytest.raises(FulfillmentRuleError):
        evaluate_incident(
            updated, target, uuid4(), NOW, responsibility, "note", description
        )


@pytest.mark.parametrize(
    "target,description",
    [
        (DecisionStatus.OPEN, None),
        (DecisionStatus.APPROVED, None),
        (DecisionStatus.APPROVED, " "),
        (DecisionStatus.REJECTED, "Not allowed"),
        ("APPROVED", "description"),
    ],
)
def test_invalid_decisions(target, description):
    with pytest.raises(FulfillmentRuleError):
        evaluate_incident(incident(), target, uuid4(), NOW, None, None, description)


@pytest.mark.parametrize(
    "mode,source,target",
    [
        (OrderMode.PICKUP, OrderStatus.SCHEDULED, OrderStatus.WAITING),
        (OrderMode.PICKUP, OrderStatus.READY_FOR_PICKUP, OrderStatus.PICKED_UP),
        (OrderMode.DELIVERY, OrderStatus.READY, OrderStatus.OUT_FOR_DELIVERY),
        (OrderMode.DELIVERY, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED),
    ],
)
def test_fulfillment_uses_orders_transition_policy(mode, source, target):
    order = record(uuid4(), mode, source)
    history = StatusHistory(
        from_status=source, to_status=target, changed_by_user_id=uuid4(), created_at=NOW
    )
    validate_fulfillment_transition(order, history)
    for changes in (
        {"payment_status": PaymentStatus.PENDING},
        {"payment_method_type": PaymentMethodType.CASH},
        {"confirmed_at": None},
    ):
        with pytest.raises(OrderRuleError):
            validate_fulfillment_transition(replace(order, **changes), history)


@pytest.mark.parametrize(
    "target",
    [
        OrderStatus.PREPARING,
        OrderStatus.READY,
        OrderStatus.CANCELLED,
        OrderStatus.SERVED,
    ],
)
def test_no_kitchen_or_cancellation_transitions(target):
    order = record(uuid4(), OrderMode.DELIVERY, OrderStatus.WAITING)
    with pytest.raises(OrderRuleError):
        validate_fulfillment_transition(
            order,
            StatusHistory(
                from_status=order.status,
                to_status=target,
                changed_by_user_id=uuid4(),
                created_at=NOW,
            ),
        )


@pytest.mark.parametrize("count,time", [(0, None), (2, NOW), (1, None)])
def test_delivered_projection_requires_unique_actual_history(count, time):
    with pytest.raises(OrderRuleError):
        record(
            uuid4(),
            OrderMode.DELIVERY,
            OrderStatus.DELIVERED,
            delivered_history_count=count,
            delivered_at=time,
        )
