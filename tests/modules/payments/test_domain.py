from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
)
from app.modules.orders.domain.payments import payment_confirmation_target
from app.modules.payments.application.dtos import (
    GatewayAttemptResult,
    VerifiedPaymentEvent,
)
from app.modules.payments.domain.models import (
    AttemptStatus,
    ClientAction,
    EventStatus,
    HistorySource,
    Payment,
    PaymentAttempt,
    PaymentRuleError,
    PaymentStatus,
    PaymentStatusHistory,
    ProviderEvent,
    VerifiedResult,
    idempotency_key,
    money,
)
from app.modules.payments.domain.transitions import (
    transition_attempt,
    transition_payment,
)
from tests.modules.payments.fakes import NOW


def payment(**changes):
    return Payment(
        order_id=uuid4(),
        method_type=PaymentMethodType.ONLINE,
        amount=Decimal("32.50"),
        **changes,
    )


@pytest.mark.parametrize(
    "amount",
    [
        0,
        1.1,
        "1.00",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-0.01"),
        Decimal("1.001"),
        Decimal("10000000000000000"),
    ],
)
def test_reject_invalid_amounts(amount):
    with pytest.raises(PaymentRuleError):
        money(amount)


@pytest.mark.parametrize(
    "amount", ["0", "0.00", "0.010", "32.50", "9999999999999999.99"]
)
def test_exact_decimal_amounts(amount):
    assert money(Decimal(amount)).as_tuple().exponent == -2


@pytest.mark.parametrize(
    "key", ["", " ", "abc def", "a" * 129, "a\n", "ñ", "https://x/a", None]
)
def test_invalid_idempotency_keys(key):
    with pytest.raises(PaymentRuleError):
        idempotency_key(key)


@pytest.mark.parametrize("key", ["a", "checkout:2", "abc_01-xy.z", "a" * 128])
def test_valid_keys(key):
    idempotency_key(key)


@pytest.mark.parametrize("source", list(PaymentStatus))
@pytest.mark.parametrize("target", list(PaymentStatus))
def test_online_transition_graph(source, target):
    p = payment(status=source, paid_at=NOW if source == PaymentStatus.PAID else None)
    allowed = {
        ("PENDING", "PROCESSING"),
        ("PROCESSING", "PAID"),
        ("PROCESSING", "FAILED"),
        ("FAILED", "PROCESSING"),
    }
    if (source, target) in allowed:
        changed = transition_payment(p, target, NOW)
        assert changed.status == target and changed.amount == p.amount
        assert changed.paid_at == (NOW if target == PaymentStatus.PAID else None)
    else:
        with pytest.raises(PaymentRuleError):
            transition_payment(p, target, NOW)


def test_cash_has_only_actual_receipt_transition():
    p = replace(payment(), method_type=PaymentMethodType.CASH)
    assert transition_payment(p, PaymentStatus.PAID, NOW).paid_at == NOW
    for target in (
        PaymentStatus.PROCESSING,
        PaymentStatus.FAILED,
        PaymentStatus.PENDING,
    ):
        with pytest.raises(PaymentRuleError):
            transition_payment(p, target, NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": PaymentStatus.PAID},
        {"paid_at": NOW},
        {"currency_code": "USD"},
        {"created_at": NOW.replace(tzinfo=None)},
        {"status": "PENDING"},
        {"reconciliation_required": 1},
        {"method_type": "ONLINE"},
        {"method_type": PaymentMethodType.CASH, "status": PaymentStatus.PROCESSING},
    ],
)
def test_payment_invariants(changes):
    with pytest.raises(PaymentRuleError):
        replace(payment(), **changes)


def attempt(**changes):
    return PaymentAttempt(
        **(
            dict(
                payment_id=uuid4(),
                idempotency_key="test",
                provider_code="test",
                amount=Decimal("32.50"),
            )
            | changes
        )
    )


@pytest.mark.parametrize("source", list(AttemptStatus))
@pytest.mark.parametrize("target", list(AttemptStatus))
def test_attempt_transition_graph(source, target):
    a = attempt(
        status=source,
        provider_reference="ref",
        completed_at=NOW
        if source in {AttemptStatus.FAILED, AttemptStatus.SUCCEEDED}
        else None,
    )
    allowed = {
        ("CREATED", "PROCESSING"),
        ("CREATED", "FAILED"),
        ("PROCESSING", "SUCCEEDED"),
        ("PROCESSING", "FAILED"),
    }
    if (source, target) in allowed:
        updated = transition_attempt(a, target, NOW)
        assert updated.id == a.id and updated.amount == a.amount
    else:
        with pytest.raises(PaymentRuleError):
            transition_attempt(a, target, NOW)


@pytest.mark.parametrize("status", [AttemptStatus.CREATED, AttemptStatus.FAILED])
def test_authenticated_late_capture_records_financial_truth(status):
    a = attempt(
        status=status,
        provider_reference="ref",
        completed_at=NOW if status == AttemptStatus.FAILED else None,
    )
    assert (
        transition_attempt(
            a, AttemptStatus.SUCCEEDED, NOW, verified_capture=True
        ).status
        == AttemptStatus.SUCCEEDED
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"status": AttemptStatus.PROCESSING},
        {"status": AttemptStatus.FAILED},
        {"completed_at": NOW},
        {"provider_code": "BAD"},
        {"failure_code": "PRIVATE ERROR"},
        {"failure_code": "DECLINED"},
        {"client_action": ClientAction(kind="SDK_TOKEN", value="test-public-token")},
    ],
)
def test_attempt_invariants(changes):
    with pytest.raises(PaymentRuleError):
        attempt(**changes)


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test",
        "javascript:alert(1)",
        "https://user:pass@example.test",
        "no-url",
        "",
        " https://example.test",
    ],
)
def test_redirect_rejects_unsafe_transport(value):
    with pytest.raises(PaymentRuleError):
        ClientAction(kind="REDIRECT", value=value)


def test_redirect_and_tokens_are_not_in_debug_representation():
    for kind, value in (
        ("REDIRECT", "https://example.test"),
        ("SDK_TOKEN", "opaque-public-client-token"),
    ):
        action = ClientAction(kind=kind, value=value)
        assert value not in repr(action)


@pytest.mark.parametrize(
    "result", [AttemptStatus.SUCCEEDED, AttemptStatus.CREATED, "PROCESSING"]
)
def test_initiation_cannot_confirm_payment(result):
    with pytest.raises(PaymentRuleError):
        GatewayAttemptResult(
            provider_code="test", provider_reference="ref", status=result
        )


@pytest.mark.parametrize(
    "source,actor",
    [
        (HistorySource.STAFF, None),
        (HistorySource.PROVIDER, uuid4()),
        (HistorySource.SYSTEM, uuid4()),
    ],
)
def test_history_actor_provenance(source, actor):
    with pytest.raises(PaymentRuleError):
        PaymentStatusHistory(
            payment_id=uuid4(),
            from_status=PaymentStatus.PROCESSING,
            to_status=PaymentStatus.PAID,
            source=source,
            changed_by_user_id=actor,
        )


@pytest.mark.parametrize(
    "mode,offset,target",
    [
        (OrderMode.LOCAL, None, OrderStatus.WAITING),
        (OrderMode.DELIVERY, None, OrderStatus.WAITING),
        (OrderMode.PICKUP, 10, OrderStatus.SCHEDULED),
        (OrderMode.PICKUP, 0, OrderStatus.WAITING),
        (OrderMode.PICKUP, -10, OrderStatus.WAITING),
    ],
)
def test_payment_policy_reuses_orders_graph(setup, mode, offset, target):
    order = replace(
        setup.order,
        mode=mode,
        calculated_kitchen_release_at=NOW + timedelta(minutes=offset)
        if offset is not None
        else None,
    )
    assert payment_confirmation_target(order, NOW, online=True) == target


def test_paid_cancelled_order_is_not_resurrected(setup):
    order = replace(setup.order, status=OrderStatus.CANCELLED)
    assert payment_confirmation_target(order, NOW, online=True) == OrderStatus.CANCELLED


def test_cash_policy_does_not_release_order(setup):
    order = replace(
        setup.order,
        payment_method_type=PaymentMethodType.CASH,
        status=OrderStatus.PENDING_CASH_CONFIRMATION,
    )
    assert payment_confirmation_target(order, NOW, online=False) == order.status


@pytest.mark.parametrize(
    "changes",
    [
        {"processing_status": EventStatus.PROCESSED},
        {"payload_hash": "fake"},
        {"processed_at": NOW},
        {"reported_currency": "pen"},
        {"result": "SUCCEEDED"},
        {"reason_code": "private text"},
    ],
)
def test_verified_event_audit_invariants(changes):
    with pytest.raises(PaymentRuleError):
        ProviderEvent(
            **(
                dict(
                    provider_code="test",
                    provider_event_id="evt",
                    provider_reference="ref",
                    payload_hash="a" * 64,
                    result=VerifiedResult.SUCCEEDED,
                    reported_amount=Decimal("32.50"),
                    reported_currency="PEN",
                    provider_occurred_at=NOW,
                )
                | changes
            )
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"result": "SUCCEEDED"},
        {"currency_code": "pe"},
        {"currency_code": "123"},
        {"occurred_at": NOW.replace(tzinfo=None)},
    ],
)
def test_internal_verified_dto_validates_values(changes):
    with pytest.raises(PaymentRuleError):
        VerifiedPaymentEvent(
            **(
                dict(
                    provider_code="test",
                    provider_event_id="evt",
                    provider_reference="ref",
                    result=VerifiedResult.SUCCEEDED,
                    amount=Decimal("32.50"),
                    currency_code="PEN",
                    occurred_at=NOW,
                )
                | changes
            )
        )
