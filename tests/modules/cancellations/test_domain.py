from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.cancellations.domain.models import (
    CancellationRequest,
    CancellationRuleError,
    CancellationSource,
    OrderCancellation,
    ReasonCode,
    RequestStatus,
    plain_text,
)
from app.modules.cancellations.domain.policies import decide_request
from app.modules.orders.domain.cancellations import (
    CANCELLABLE_STATUSES,
    validate_cancellation,
)
from app.modules.orders.domain.models import OrderRuleError, OrderStatus
from tests.modules.cancellations.fakes import cancellation_setup
from tests.modules.payments.fakes import NOW


@pytest.mark.parametrize("status", list(OrderStatus))
def test_cancellation_has_separate_policy(status):
    order = replace(cancellation_setup().order, status=status)
    if status in CANCELLABLE_STATUSES:
        validate_cancellation(order)
    else:
        with pytest.raises(OrderRuleError):
            validate_cancellation(order)


@pytest.mark.parametrize(
    "reason",
    [
        "",
        " ",
        "<script>alert(1)</script>",
        "a>b",
        "line\nnext",
        "x\x00",
        "x\u200b",
        "x" * 1001,
        None,
        123,
    ],
)
def test_plain_text_rejects_unsafe_input(reason):
    with pytest.raises(CancellationRuleError):
        plain_text(reason)


def request():
    return CancellationRequest(
        order_id=uuid4(),
        customer_id=uuid4(),
        branch_id=uuid4(),
        reason="Change of plans",
        requested_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("target", [RequestStatus.APPROVED, RequestStatus.REJECTED])
def test_decision_is_terminal_and_exactly_idempotent(target):
    r = request()
    actor = uuid4()
    changed = decide_request(r, target, actor, NOW, "Checked")
    assert r.status == RequestStatus.PENDING
    assert decide_request(changed, target, actor, NOW, " Checked ") == changed
    for bad_actor, bad_note in ((uuid4(), "Checked"), (actor, "Different")):
        with pytest.raises(CancellationRuleError):
            decide_request(changed, target, bad_actor, NOW, bad_note)
    with pytest.raises(CancellationRuleError):
        decide_request(changed, RequestStatus.PENDING, actor, NOW, None)


@pytest.mark.parametrize(
    "changes",
    [
        {"evaluated_by_user_id": uuid4()},
        {"evaluation_note": "A note"},
        {"evaluated_at": NOW},
        {"status": RequestStatus.APPROVED},
        {"requested_at": NOW.replace(tzinfo=None)},
        {"reason": " untrimmed "},
    ],
)
def test_request_invariants(changes):
    with pytest.raises(CancellationRuleError):
        replace(request(), **changes)


def test_evaluation_cannot_predate_request():
    with pytest.raises(CancellationRuleError):
        decide_request(
            request(), RequestStatus.APPROVED, uuid4(), NOW - timedelta(seconds=1), None
        )


@pytest.mark.parametrize("code", list(ReasonCode))
def test_direct_reason_provenance(code):
    args = dict(
        order_id=uuid4(),
        branch_id=uuid4(),
        source=CancellationSource.ADMIN,
        reason_code=code,
        cancelled_by_user_id=uuid4(),
        cancelled_at=NOW,
    )
    if code == ReasonCode.OUT_OF_STOCK:
        OrderCancellation(**args)
    else:
        with pytest.raises(CancellationRuleError):
            OrderCancellation(**args)


def test_admin_cannot_link_request():
    with pytest.raises(CancellationRuleError):
        OrderCancellation(
            order_id=uuid4(),
            branch_id=uuid4(),
            source=CancellationSource.ADMIN,
            reason_code=ReasonCode.OUT_OF_STOCK,
            cancellation_request_id=uuid4(),
            cancelled_by_user_id=uuid4(),
            cancelled_at=NOW,
        )


def test_decimal_preserved():
    assert cancellation_setup(total=Decimal("0.00")).order.total == Decimal("0.00")
