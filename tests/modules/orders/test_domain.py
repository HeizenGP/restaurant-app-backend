import asyncio
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import (
    BranchOrderSettings,
    DeliveryZone,
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    PickupDetails,
    money,
)
from app.modules.orders.domain.policies import (
    initial_status,
    pickup_times,
    within_branch_hours,
)
from app.modules.orders.domain.transitions import (
    flow,
    status_after_payment,
    validate_transition,
)


@pytest.mark.parametrize(
    "value",
    [
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("0.001"),
        Decimal("10000000000000000.00"),
        2.5,
        2,
        "2.00",
    ],
)
def test_money_rejects_invalid_or_non_decimal_values(value):
    with pytest.raises(OrderRuleError):
        money(value)


@pytest.mark.parametrize("value", ["0", "1.20", "9999999999999999.99"])
def test_money_accepts_finite_exact_values(value):
    assert money(Decimal(value)) == Decimal(value)


@pytest.mark.parametrize(
    "mode,method,confirm,status",
    [
        ("LOCAL", "ONLINE", True, "PENDING_PAYMENT"),
        ("LOCAL", "CASH", True, "PENDING_CASH_CONFIRMATION"),
        ("LOCAL", "CASH", False, "WAITING"),
        ("PICKUP", "ONLINE", True, "PENDING_PAYMENT"),
        ("DELIVERY", "ONLINE", True, "PENDING_PAYMENT"),
    ],
)
def test_initial_payment_policy(mode, method, confirm, status):
    settings = BranchOrderSettings(
        branch_id=uuid4(), cash_payment_requires_confirmation=confirm
    )
    assert initial_status(
        OrderMode(mode), PaymentMethodType(method), settings
    ) == OrderStatus(status)


@pytest.mark.parametrize("mode", [OrderMode.PICKUP, OrderMode.DELIVERY])
def test_cash_is_local_only(mode):
    with pytest.raises(OrderRuleError):
        initial_status(
            mode, PaymentMethodType.CASH, BranchOrderSettings(branch_id=uuid4())
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"timezone": "Invalid/Zone"},
        {"default_prep_minutes": 0},
        {"pickup_buffer_minutes": -1},
        {"queue_delay_per_order_minutes": 1441},
        {"delivery_default_travel_minutes": 1.5},
        {"delivery_minimum_order": Decimal("-1")},
        {"cash_payment_requires_confirmation": 1},
    ],
)
def test_settings_invariants(changes):
    with pytest.raises(OrderRuleError):
        BranchOrderSettings(branch_id=uuid4(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"is_free": True, "delivery_fee": Decimal("1.00")},
        {"delivery_fee": Decimal("-1")},
        {"district": " Tarapoto"},
        {"estimated_travel_minutes": -1},
    ],
)
def test_zone_invariants(changes):
    values = dict(
        branch_id=None, name="Zone", district="Tarapoto", delivery_fee=Decimal("0.00")
    )
    with pytest.raises(OrderRuleError):
        DeliveryZone(**(values | changes))


def test_pickup_formula_and_aware_timestamps():
    now = datetime(2026, 10, 6, 17, tzinfo=UTC)
    requested = now + timedelta(hours=2)
    release, ready = pickup_times(now, requested, 35, 5)
    assert release == requested - timedelta(minutes=40)
    assert ready == requested - timedelta(minutes=5)
    with pytest.raises(OrderRuleError):
        pickup_times(now, requested.replace(tzinfo=None), 35, 5)


@pytest.mark.parametrize("minutes", [-10, 0, 24])
def test_pickup_impossible(minutes):
    now = datetime(2026, 10, 6, 17, tzinfo=UTC)
    with pytest.raises(OrderRuleError):
        pickup_times(now, now + timedelta(minutes=minutes), 20, 5)


@pytest.mark.parametrize(
    "hour,expected", [(9, False), (10, True), (17, True), (18, False)]
)
def test_local_branch_hours_use_configured_timezone(hour, expected):
    requested = datetime(2026, 10, 6, hour + 5, tzinfo=UTC)
    hours = ((1, time(10), time(18), False),)
    assert within_branch_hours(requested, "America/Lima", hours) is expected


def test_overnight_hours_and_no_hours_fallback():
    late = datetime(2026, 10, 7, 1, tzinfo=UTC)
    hours = ((1, time(18), time(2), False),)
    assert within_branch_hours(late, "UTC", hours)
    assert not within_branch_hours(late + timedelta(hours=2), "UTC", hours)
    assert within_branch_hours(late, "America/Lima", ())
    assert not within_branch_hours(late, "UTC", ((2, None, None, True),))


@pytest.fixture
def order(setup):
    return asyncio.run(setup.service.create(setup.cart.guest, "domain", setup.local()))


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "LOCAL"},
        {"status": "WAITING"},
        {"payment_status": "PENDING"},
        {"subtotal": Decimal("0.00")},
        {"total": Decimal("0.00")},
        {"items": ()},
        {"delivery_fee": Decimal("1.00")},
        {"local_details": None},
        {"status": OrderStatus.DELIVERED},
    ],
)
def test_order_invariants(order, changes):
    with pytest.raises(OrderRuleError):
        replace(order, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": 0},
        {"quantity": 10001},
        {"quantity": True},
        {"unit_price_snapshot": Decimal("99.00")},
        {"line_total_snapshot": Decimal("0.00")},
        {"addons_price_snapshot": Decimal("1.00")},
        {"product_name_snapshot": ""},
    ],
)
def test_item_snapshots_are_consistent(order, changes):
    with pytest.raises(OrderRuleError):
        replace(order.items[0], **changes)


def test_cash_transition_does_not_require_paid(order):
    validate_transition(order, OrderStatus.WAITING)
    with pytest.raises(OrderRuleError):
        validate_transition(order, OrderStatus.PREPARING)
    with pytest.raises(OrderRuleError):
        validate_transition(
            replace(order, status=OrderStatus.SERVED), OrderStatus.WAITING
        )


def test_online_payment_gate_and_future_pickup_activation(order, setup):
    online = replace(
        order,
        payment_method_type=PaymentMethodType.ONLINE,
        status=OrderStatus.PENDING_PAYMENT,
        local_details=replace(
            order.local_details, payment_choice=PaymentMethodType.ONLINE
        ),
    )
    with pytest.raises(OrderRuleError):
        validate_transition(online, OrderStatus.WAITING)
    validate_transition(
        replace(online, payment_status=PaymentStatus.PAID), OrderStatus.WAITING
    )
    assert status_after_payment(online, setup.now) == OrderStatus.WAITING
    pickup = PickupDetails(
        requested_pickup_at=setup.now + timedelta(hours=1),
        calculated_kitchen_release_at=setup.now + timedelta(minutes=35),
        estimated_ready_at=setup.now + timedelta(minutes=55),
        pickup_name_snapshot="Customer",
        pickup_phone_snapshot="+51900000111",
    )
    scheduled = replace(
        online, mode=OrderMode.PICKUP, local_details=None, pickup_details=pickup
    )
    assert status_after_payment(scheduled, setup.now) == OrderStatus.SCHEDULED
    assert (
        status_after_payment(scheduled, pickup.calculated_kitchen_release_at)
        == OrderStatus.WAITING
    )


@pytest.mark.parametrize(
    "mode,terminal",
    [
        (OrderMode.LOCAL, OrderStatus.SERVED),
        (OrderMode.PICKUP, OrderStatus.PICKED_UP),
        (OrderMode.DELIVERY, OrderStatus.DELIVERED),
    ],
)
def test_mode_transition_graphs_have_distinct_terminal_states(mode, terminal):
    route = flow(mode, PaymentMethodType.ONLINE)
    assert route[0] == OrderStatus.PENDING_PAYMENT and route[-1] == terminal


def test_unpaid_online_order_cannot_be_active_even_if_constructed_directly(order):
    with pytest.raises(OrderRuleError):
        replace(
            order,
            payment_method_type=PaymentMethodType.ONLINE,
            local_details=replace(
                order.local_details, payment_choice=PaymentMethodType.ONLINE
            ),
            status=OrderStatus.WAITING,
        )


def test_two_modalities_cannot_coexist(order, setup):
    details = PickupDetails(
        requested_pickup_at=setup.now + timedelta(hours=1),
        calculated_kitchen_release_at=setup.now + timedelta(minutes=35),
        estimated_ready_at=setup.now + timedelta(minutes=55),
        pickup_name_snapshot="Customer",
        pickup_phone_snapshot="+51900000111",
    )
    with pytest.raises(OrderRuleError):
        replace(order, pickup_details=details)
