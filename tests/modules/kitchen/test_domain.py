from dataclasses import replace
from datetime import timedelta

import pytest

from app.modules.kitchen.application.dtos import KitchenQueueQuery, group_queue
from app.modules.kitchen.domain.models import (
    KitchenDataError,
    target_ready_status,
    timing_for,
)
from app.modules.orders.domain.lifecycle import validate_preparation_transition
from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    StatusHistory,
)
from tests.modules.kitchen.fakes import (
    NOW,
    READY_AT,
    WAITING_AT,
    context,
    record,
    snapshot,
)


@pytest.mark.parametrize(
    "mode,target",
    [
        (OrderMode.LOCAL, OrderStatus.READY),
        (OrderMode.DELIVERY, OrderStatus.READY),
        (OrderMode.PICKUP, OrderStatus.READY_FOR_PICKUP),
    ],
)
def test_mode_specific_target(mode, target):
    assert target_ready_status(mode) == target


def test_unknown_mode_is_not_treated_as_local():
    with pytest.raises(KitchenDataError):
        target_ready_status("LOCAL")


@pytest.mark.parametrize(
    "status,clock,expected",
    [
        (OrderStatus.WAITING, WAITING_AT + timedelta(minutes=5), (300, 0, 300)),
        (OrderStatus.PREPARING, WAITING_AT + timedelta(minutes=10), (240, 360, 360)),
        (OrderStatus.READY, NOW, (240, 420, 540)),
    ],
)
def test_timers_use_history_not_order_creation(status, clock, expected):
    timing = timing_for(snapshot(record(status=status)), clock)
    assert (
        timing.waiting_seconds,
        timing.preparation_seconds,
        timing.current_status_seconds,
    ) == expected


def test_pickup_ready_timer_uses_correct_ready_history():
    timing = timing_for(
        snapshot(record(mode=OrderMode.PICKUP, status=OrderStatus.READY_FOR_PICKUP)),
        NOW,
    )
    assert timing.ready_at == READY_AT and timing.preparation_seconds == 420


@pytest.mark.parametrize(
    "status", [OrderStatus.WAITING, OrderStatus.PREPARING, OrderStatus.READY]
)
def test_clock_skew_never_produces_negative_durations(status):
    timing = timing_for(
        snapshot(record(status=status)), WAITING_AT - timedelta(minutes=1)
    )
    assert (
        min(
            timing.waiting_seconds,
            timing.preparation_seconds,
            timing.current_status_seconds,
        )
        >= 0
    )


@pytest.mark.parametrize(
    "status", [OrderStatus.WAITING, OrderStatus.PREPARING, OrderStatus.READY]
)
def test_missing_history_is_not_fabricated_from_created_at(status):
    row = record(status=status)
    row.history = row.history[:-1]
    with pytest.raises(KitchenDataError):
        timing_for(snapshot(row), NOW)


def test_naive_clock_and_history_are_rejected():
    row = snapshot(record())
    with pytest.raises(KitchenDataError):
        timing_for(row, NOW.replace(tzinfo=None))
    row = replace(
        row,
        history=(replace(row.history[0], created_at=WAITING_AT.replace(tzinfo=None)),),
    )
    with pytest.raises(KitchenDataError):
        timing_for(row, NOW)


def test_duplicate_and_backward_history_are_integrity_errors():
    row = snapshot(record(status=OrderStatus.PREPARING))
    with pytest.raises(KitchenDataError):
        timing_for(replace(row, history=(*row.history, row.history[-1])), NOW)
    backward = replace(row.history[-1], created_at=WAITING_AT - timedelta(seconds=1))
    with pytest.raises(KitchenDataError):
        timing_for(replace(row, history=(row.history[0], backward)), NOW)


def test_equal_timestamps_can_be_valid_without_random_uuid_ordering():
    row = snapshot(record(status=OrderStatus.PREPARING))
    history = tuple(replace(entry, created_at=WAITING_AT) for entry in row.history)
    assert timing_for(replace(row, history=history), NOW).waiting_seconds == 0


def test_grouping_ordering_and_ready_modes():
    rows = [
        snapshot(record(status=OrderStatus.READY, number=8)),
        snapshot(record(number=3)),
        snapshot(record(number=1)),
        snapshot(record(status=OrderStatus.PREPARING, number=4)),
        snapshot(
            record(mode=OrderMode.PICKUP, status=OrderStatus.READY_FOR_PICKUP, number=5)
        ),
    ]
    queue = group_queue(rows, NOW, KitchenQueueQuery())
    assert [row.order_number for row in queue.waiting] == [1, 3]
    assert [row.order_number for row in queue.preparing] == [4]
    assert [row.order_number for row in queue.ready] == [5, 8]
    assert queue.generated_at == NOW


@pytest.mark.parametrize(
    "updates",
    [
        {"limit": 0},
        {"limit": 201},
        {"limit": True},
        {"offset": -1},
        {"offset": 100001},
        {"status": OrderStatus.CANCELLED},
        {"mode": "LOCAL"},
    ],
)
def test_queue_query_bounds(updates):
    with pytest.raises(ValueError):
        KitchenQueueQuery(**updates)


@pytest.mark.parametrize(
    "target",
    [
        OrderStatus.CANCELLED,
        OrderStatus.SERVED,
        OrderStatus.PICKED_UP,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
        OrderStatus.WAITING,
    ],
)
def test_orders_internal_preparation_contract_rejects_other_operations(target):
    row = record(status=OrderStatus.PREPARING)
    history = StatusHistory(
        from_status=row.status,
        to_status=target,
        changed_by_user_id=row.id,
        created_at=NOW,
    )
    with pytest.raises(OrderRuleError):
        validate_preparation_transition(context(row), history)
