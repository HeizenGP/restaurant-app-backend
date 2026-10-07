from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.domain.models import PaymentRuleError, PaymentStatus
from app.modules.payments.domain.refunds import (
    Refund,
    RefundHistorySource,
    RefundStatus,
    RefundStatusHistory,
    transition_refund,
    validate_full_refund,
)
from tests.modules.cancellations.fakes import cancellation_setup
from tests.modules.payments.fakes import NOW


def refund(status=RefundStatus.PENDING, method=PaymentMethodType.ONLINE):
    return Refund(
        payment_id=uuid4(),
        order_id=uuid4(),
        amount=Decimal("32.50"),
        method_type=method,
        status=status,
        requested_at=NOW,
        refunded_at=NOW if status == RefundStatus.REFUNDED else None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("source", list(RefundStatus))
@pytest.mark.parametrize("target", list(RefundStatus))
def test_online_graph(source, target):
    allowed = {
        ("PENDING", "PROCESSING"),
        ("PROCESSING", "REFUNDED"),
        ("PROCESSING", "FAILED"),
        ("FAILED", "PROCESSING"),
    }
    r = refund(source)
    if (source.value, target.value) in allowed:
        assert transition_refund(r, target, NOW).status == target
    else:
        with pytest.raises(PaymentRuleError):
            transition_refund(r, target, NOW)


@pytest.mark.parametrize("target", list(RefundStatus))
def test_cash_graph(target):
    r = refund(method=PaymentMethodType.CASH)
    if target == RefundStatus.REFUNDED:
        assert transition_refund(r, target, NOW).refunded_at == NOW
    else:
        with pytest.raises(PaymentRuleError):
            transition_refund(r, target, NOW)


@pytest.mark.parametrize(
    "amount",
    [Decimal("-1"), Decimal("1.001"), 1, 1.2, Decimal("NaN"), Decimal("Infinity")],
)
def test_refund_uses_strict_money(amount):
    with pytest.raises(PaymentRuleError):
        replace(refund(), amount=amount)


@pytest.mark.parametrize(
    "changes",
    [
        {"currency_code": "USD"},
        {"reason_code": "PARTIAL"},
        {"status": RefundStatus.REFUNDED},
        {"refunded_at": NOW},
        {"reconciliation_required": 1},
        {"requested_at": NOW.replace(tzinfo=None)},
    ],
)
def test_refund_financial_shape(changes):
    with pytest.raises(PaymentRuleError):
        replace(refund(), **changes)


@pytest.mark.parametrize("mismatch", ["amount", "order", "method", "status"])
def test_full_refund_requires_original_paid_truth(mismatch):
    s = cancellation_setup()
    p = next(iter(s.db.payments.values()))
    changes = (
        {"amount": Decimal("1.00")}
        if mismatch == "amount"
        else {"order_id": uuid4()}
        if mismatch == "order"
        else {"method_type": PaymentMethodType.CASH}
        if mismatch == "method"
        else {"status": PaymentStatus.PENDING, "paid_at": None}
    )
    p = replace(p, **changes)
    with pytest.raises(PaymentRuleError):
        validate_full_refund(p, s.order.id, s.order.total, s.order.payment_method_type)


@pytest.mark.parametrize("source", list(RefundHistorySource))
def test_history_actor_required_only_for_staff(source):
    args = dict(
        refund_id=uuid4(),
        from_status=RefundStatus.PENDING,
        to_status=RefundStatus.PROCESSING,
        source=source,
        created_at=NOW,
    )
    RefundStatusHistory(
        **args,
        changed_by_user_id=uuid4() if source == RefundHistorySource.STAFF else None,
    )
    with pytest.raises(PaymentRuleError):
        RefundStatusHistory(
            **args,
            changed_by_user_id=None if source == RefundHistorySource.STAFF else uuid4(),
        )


def test_zero_is_explicit_obligation():
    assert replace(refund(), amount=Decimal("0.00")).status == RefundStatus.PENDING
