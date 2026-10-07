import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.modules.orders.domain.models import (
    OrderStatus,
    PaymentMethodType,
)
from app.modules.orders.infrastructure.payments import SQLAlchemyOrderPaymentRepository
from app.modules.payments.application.errors import (
    PaymentConflictError,
    PaymentDataError,
)
from app.modules.payments.domain.models import (
    AttemptStatus,
    Payment,
    PaymentAttempt,
    PaymentStatus,
    ProviderEvent,
    VerifiedResult,
)
from app.modules.payments.infrastructure.persistence.models import (
    PaymentAttemptModel,
    PaymentModel,
    PaymentProviderEventModel,
)
from app.modules.payments.infrastructure.persistence.repositories import (
    SQLAlchemyPaymentRepository,
    attempt_domain,
    attempt_values,
    event_domain,
    payment_domain,
)
from tests.modules.payments.fakes import NOW


def run(awaitable):
    return asyncio.run(awaitable)


def sql(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def session():
    value = MagicMock()
    value.execute = AsyncMock(return_value=MagicMock())
    value.flush = AsyncMock()
    value.commit = AsyncMock()
    value.rollback = AsyncMock()
    return value


def payment():
    from decimal import Decimal

    return Payment(
        order_id=uuid4(),
        method_type=PaymentMethodType.ONLINE,
        amount=Decimal("32.50"),
        created_at=NOW,
        updated_at=NOW,
    )


def attempt(p):
    return PaymentAttempt(
        payment_id=p.id,
        idempotency_key="test",
        provider_code="test",
        amount=p.amount,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("method", ["owned", "branch", "global"])
def test_order_context_sql_filters_before_lock_and_has_no_private_projection(
    setup, method
):
    s = session()
    s.execute.return_value.mappings.return_value.one_or_none.return_value = None
    repo = SQLAlchemyOrderPaymentRepository(s)
    kwargs = {"lock": True}
    if method == "owned":
        kwargs["customer_id"] = setup.customer.customer_id
    if method == "branch":
        kwargs["branch_id"] = setup.order.branch_id
    assert run(repo.payment_context(setup.order.id, **kwargs)) is None
    query = sql(s.execute.call_args.args[0])
    assert "FOR UPDATE OF orders" in query
    assert str(setup.order.id) in query
    if method == "owned":
        assert "orders.customer_id =" in query
    if method == "branch":
        assert "orders.branch_id =" in query
    for hidden in (
        "phone",
        "address_line",
        "product_name",
        "card_number",
        "order_items",
    ):
        assert hidden not in query


def test_order_context_maps_minimal_valid_context(setup):
    s = session()
    s.execute.return_value.mappings.return_value.one_or_none.return_value = asdict(
        setup.order
    )
    result = run(
        SQLAlchemyOrderPaymentRepository(s).payment_context(setup.order.id, lock=True)
    )
    assert result == setup.order


@pytest.mark.parametrize(
    "online,cancelled", [(False, False), (True, False), (True, True)]
)
def test_paid_order_write_is_conditional_no_repository_commit(setup, online, cancelled):
    from dataclasses import replace

    order = setup.order
    if not online:
        order = replace(
            order,
            payment_method_type=PaymentMethodType.CASH,
            status=OrderStatus.PENDING_CASH_CONFIRMATION,
        )
    if cancelled:
        order = replace(order, status=OrderStatus.CANCELLED)
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = order.id
    run(SQLAlchemyOrderPaymentRepository(s).confirm_payment(order, NOW, online=online))
    query = sql(s.execute.call_args.args[0])
    assert "orders.customer_id =" in query and "orders.branch_id =" in query
    assert "orders.total =" in query and "orders.status =" in query
    assert "payment_status='PAID'" in query
    if not online or cancelled:
        assert "confirmed_at=" not in query and "SET status=" not in query
        s.add.assert_not_called()
    else:
        assert "status='WAITING'" in query and "confirmed_at=" in query
        history = s.add.call_args.args[0]
        assert (
            history.changed_by_user_id is None
            and history.from_status == "PENDING_PAYMENT"
        )
    s.commit.assert_not_awaited()


def test_payment_owned_read_uses_sql_join_scope_before_any_attempt_read(setup):
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = None
    assert (
        run(
            SQLAlchemyPaymentRepository(s).get_owned(
                setup.customer.customer_id, setup.order.id
            )
        )
        is None
    )
    query = sql(s.execute.call_args.args[0])
    assert (
        "JOIN orders" in query
        and "orders.customer_id =" in query
        and "orders.id =" in query
    )
    assert s.execute.await_count == 1


def test_payment_and_attempt_locks_are_explicit():
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = None
    repo = SQLAlchemyPaymentRepository(s)
    run(repo.payment_for_order(uuid4(), lock=True))
    assert "FOR UPDATE" in sql(s.execute.call_args.args[0])
    pid, aid = uuid4(), uuid4()
    run(repo.attempt_by_id(pid, aid, lock=True))
    query = sql(s.execute.call_args.args[0])
    assert str(pid) in query and str(aid) in query and "FOR UPDATE" in query


@pytest.mark.parametrize("kind", ["key", "active"])
def test_attempt_queries_are_scoped_to_payment(kind):
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = None
    repo = SQLAlchemyPaymentRepository(s)
    pid = uuid4()
    run(repo.attempt_by_key(pid, "key") if kind == "key" else repo.active_attempt(pid))
    query = sql(s.execute.call_args.args[0])
    assert str(pid) in query
    assert (
        "idempotency_key =" in query
        if kind == "key"
        else "status IN ('CREATED', 'PROCESSING')" in query
    )


def test_attempt_locator_does_not_take_attempt_lock_before_order_lock():
    s = session()
    s.execute.return_value.mappings.return_value.one_or_none.return_value = None
    run(SQLAlchemyPaymentRepository(s).attempt_locator("test", "ref"))
    query = sql(s.execute.call_args.args[0])
    assert (
        "JOIN payments" in query
        and "provider_code =" in query
        and "provider_reference =" in query
    )
    assert "FOR UPDATE" not in query


def test_payment_attempt_view_is_bounded_and_deterministically_ordered():
    s = session()
    s.execute.return_value.scalars.return_value.all.return_value = []
    view = run(SQLAlchemyPaymentRepository(s).view(payment()))
    query = sql(s.execute.call_args.args[0])
    assert "LIMIT 100" in query and "created_at DESC" in query and "id DESC" in query
    assert view.attempts == ()


def test_conditional_payment_update_does_not_mutate_historical_amount():
    from dataclasses import replace

    p = payment()
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = PaymentModel(**asdict(p))
    run(
        SQLAlchemyPaymentRepository(s).save_payment(
            p, replace(p, status=PaymentStatus.PROCESSING)
        )
    )
    query = sql(s.execute.call_args.args[0])
    assert (
        "payments.status = 'PENDING'" in query
        and "payments.reconciliation_required = false" in query
    )
    assert (
        "amount=" not in query
        and "order_id=" not in query
        and "method_type=" not in query
    )
    s.commit.assert_not_awaited()


def test_attempt_update_only_mutable_fields_with_expected_status():
    from dataclasses import replace

    a = attempt(payment())
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = PaymentAttemptModel(
        **attempt_values(a)
    )
    run(
        SQLAlchemyPaymentRepository(s).save_attempt(
            a, replace(a, status=AttemptStatus.PROCESSING, provider_reference="ref")
        )
    )
    query = sql(s.execute.call_args.args[0])
    assert (
        "payment_attempts.status = 'CREATED'" in query
        and "payment_attempts.payment_id =" in query
    )
    update = query.split(" WHERE ")[0]
    for fixed in ("amount=", "idempotency_key=", "provider_code=", "payment_id="):
        assert fixed not in update


@pytest.mark.parametrize("kind", ["payment", "attempt"])
def test_conditional_conflict_is_safe(kind):
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = None
    p = payment()
    repo = SQLAlchemyPaymentRepository(s)
    with pytest.raises(PaymentConflictError):
        run(
            repo.save_payment(p, p)
            if kind == "payment"
            else repo.save_attempt(attempt(p), attempt(p))
        )


def event():
    from decimal import Decimal

    return ProviderEvent(
        provider_code="test",
        provider_event_id="evt",
        provider_reference="ref",
        payload_hash="a" * 64,
        result=VerifiedResult.SUCCEEDED,
        reported_amount=Decimal("32.50"),
        reported_currency="PEN",
        provider_occurred_at=NOW,
        received_at=NOW,
    )


def test_provider_dedupe_is_database_on_conflict():
    e = event()
    s = session()
    s.execute.return_value.scalar_one_or_none.return_value = PaymentProviderEventModel(
        **asdict(e)
    )
    assert run(SQLAlchemyPaymentRepository(s).get_or_insert_event(e)) == e
    query = sql(s.execute.call_args.args[0])
    assert (
        "ON CONFLICT ON CONSTRAINT uq_payment_provider_events_key DO NOTHING" in query
    )
    assert "RETURNING" in query and "payload_hash" in query and "raw_body" not in query
    s.commit.assert_not_awaited()


def test_existing_provider_event_is_locked_by_its_provider_and_id():
    e = event()
    s = session()
    first, second = MagicMock(), MagicMock()
    first.scalar_one_or_none.return_value = None
    second.scalar_one.return_value = PaymentProviderEventModel(**asdict(e))
    s.execute.side_effect = [first, second]
    assert run(SQLAlchemyPaymentRepository(s).get_or_insert_event(e)) == e
    query = sql(s.execute.call_args.args[0])
    assert (
        "FOR UPDATE" in query
        and "provider_code =" in query
        and "provider_event_id =" in query
    )


@pytest.mark.parametrize(
    "model,mapper,data",
    [
        (
            PaymentModel,
            payment_domain,
            lambda: asdict(payment()) | {"currency_code": "USD"},
        ),
        (
            PaymentAttemptModel,
            attempt_domain,
            lambda: attempt_values(attempt(payment())) | {"status": "PROCESSING"},
        ),
        (
            PaymentProviderEventModel,
            event_domain,
            lambda: asdict(event()) | {"payload_hash": "invalid"},
        ),
    ],
)
def test_corrupt_persistence_data_is_a_safe_503(model, mapper, data):
    with pytest.raises(PaymentDataError):
        mapper(model(**data()))


@pytest.mark.parametrize("operation", ["flush", "commit"])
def test_database_integrity_error_does_not_leak_provider_or_sql(operation):
    s = session()
    getattr(s, operation).side_effect = IntegrityError(
        "private sql", {"secret": "private"}, Exception("private provider")
    )
    repo = SQLAlchemyPaymentRepository(s)
    with pytest.raises(PaymentConflictError) as err:
        run(repo.insert_payment(payment()) if operation == "flush" else repo.commit())
    assert "private" not in str(err.value)
