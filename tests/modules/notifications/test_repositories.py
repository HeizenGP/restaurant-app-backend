from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.modules.notifications.application.dtos import PushClaim, PushResult
from app.modules.notifications.application.errors import (
    DeviceBusyError,
    DeviceConflictError,
    NotificationDataError,
)
from app.modules.notifications.domain.models import PushDeliveryStatus as S
from app.modules.notifications.domain.models import PushResultKind
from app.modules.notifications.infrastructure.persistence.models import (
    CustomerNotificationModel as N,
)
from app.modules.notifications.infrastructure.persistence.models import (
    NotificationDeviceModel as D,
)
from app.modules.notifications.infrastructure.persistence.models import (
    NotificationPushDeliveryModel as P,
)
from app.modules.notifications.infrastructure.persistence.models import (
    RealtimeOrderEventModel as E,
)
from app.modules.notifications.infrastructure.persistence.push import (
    SQLAlchemyPushRepository,
)
from app.modules.notifications.infrastructure.persistence.repositories import (
    SQLAlchemyNotificationRepository,
    cancel_unsent,
    delivery_domain,
    device_domain,
    event_domain,
    notification_domain,
)
from app.modules.notifications.infrastructure.realtime import SQLAlchemyStreamReader
from app.modules.orders.domain.models import OrderStatus
from tests.modules.notifications.fakes import NOW, delivery, device, event, notification

pytestmark = pytest.mark.anyio


def result(value=None, rows=None, mappings=None):
    r = MagicMock()
    r.scalar_one.return_value = value
    r.scalar_one_or_none.return_value = value
    r.scalars.return_value.all.return_value = rows or []
    r.all.return_value = rows or []
    r.mappings.return_value.all.return_value = mappings or []
    r.rowcount = 0
    return r


def session(*values):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(values) or None, return_value=result())
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock()
    return db


def sql(statement):
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True}
        )
    )


def statements(db):
    return [sql(c.args[0]) for c in db.execute.call_args_list]


async def test_list_sql_watermark_first_then_owner_limit_before_desc():
    db = session(result(0), result(rows=[]))
    owner = uuid4()
    await SQLAlchemyNotificationRepository(db).list_owned(owner, 10, 50)
    first, second = statements(db)
    assert "max(" in first and "customer_notifications.customer_id =" in first
    assert "customer_notifications.customer_id =" in second
    assert "sequence_id <" in second and "sequence_id DESC" in second
    assert "LIMIT" in second and "OFFSET" not in second
    db.commit.assert_not_awaited()


async def test_unread_is_sql_count_and_read_all_single_update_owner_scoped():
    db = session(result(3), result())
    repo = SQLAlchemyNotificationRepository(db)
    assert await repo.unread_count(uuid4()) == 3
    assert await repo.mark_all_read(uuid4(), NOW) == 0
    first, second = statements(db)
    assert "count(*)" in first and "read_at IS NULL" in first
    assert second.startswith("UPDATE customer_notifications")
    assert "customer_id =" in second and "read_at IS NULL" in second
    assert "greatest(" in second and "DELETE" not in second


async def test_mark_read_update_and_idempotent_fallback_both_owner_scoped():
    n = notification()
    db = session(result(), result(N(**asdict(n))))
    assert (
        await SQLAlchemyNotificationRepository(db).mark_read(n.customer_id, n.id, NOW)
        == n
    )
    for stmt in statements(db):
        assert "customer_id =" in stmt and "customer_notifications.id =" in stmt
    assert "read_at IS NULL" in statements(db)[0]


async def test_events_and_customer_stream_bound_snapshot_cursor_branch_owner():
    db = session(result(), result())
    repo = SQLAlchemyNotificationRepository(db)
    await repo.events(uuid4(), 3, 100, until=20)
    await repo.stream_notifications(uuid4(), 3, 20, 100)
    first, second = statements(db)
    assert "branch_id =" in first and "id >" in first and "id <=" in first
    assert "customer_id =" in second and "sequence_id >" in second
    assert "sequence_id <=" in second and "ORDER BY" in first + second


async def test_admin_snapshot_minimal_batched_projection_and_terminal_filter():
    db = session(result(0), result(), result(0), result())
    repo = SQLAlchemyNotificationRepository(db)
    await repo.admin_snapshot(uuid4(), None, 0, 100)
    await repo.admin_snapshot(uuid4(), OrderStatus.CANCELLED, 0, 100)
    query = statements(db)[1]
    assert "orders.branch_id =" in query and "orders.status IN" in query
    assert "orders.order_number >" in query and "LIMIT" in query
    assert "orders.status =" in statements(db)[3]
    for forbidden in [
        "phone",
        "address",
        "payment_attempt",
        "catalog",
        "orders.total",
        "idempotency",
        "customer_id",
        "order_items",
    ]:
        assert forbidden not in query


async def test_missing_scope_rejected_not_global_max():
    with pytest.raises(NotificationDataError):
        await SQLAlchemyNotificationRepository(session()).high_watermark()


async def test_register_new_installation_upsert_scoped_no_backfill():
    d = device()
    db = session(result(D(**asdict(d))))
    value = await SQLAlchemyNotificationRepository(db).register_device(
        d.customer_id, d.installation_id, d.platform, d.provider_code, d.push_token, NOW
    )
    assert value == d
    query = statements(db)[0]
    assert "ON CONFLICT ON CONSTRAINT uq_notification_devices_installation" in query
    assert "RETURNING" in query and "notification_push_deliveries" not in query


async def test_busy_rebind_fails_under_device_row_lock_before_cancelling():
    d = device(send_locked_until=NOW + timedelta(seconds=120))
    db = session(result(), result(D(**asdict(d))))
    with pytest.raises(DeviceBusyError):
        await SQLAlchemyNotificationRepository(db).register_device(
            uuid4(), d.installation_id, d.platform, d.provider_code, d.push_token, NOW
        )
    assert len(statements(db)) == 2 and "FOR UPDATE" in statements(db)[1]


async def test_rotated_device_cancels_unsent_before_version_update():
    d = device()
    updated = replace(d, push_token="rotated", generation=2)
    db = session(
        result(),
        result(D(**asdict(d))),
        result(),
        result(),
        result(D(**asdict(updated))),
    )
    assert (
        await SQLAlchemyNotificationRepository(db).register_device(
            d.customer_id,
            d.installation_id,
            d.platform,
            d.provider_code,
            "rotated",
            NOW,
        )
        == updated
    )
    stmts = statements(db)
    assert stmts[3].startswith("UPDATE notification_push_deliveries")
    assert "status IN" in stmts[3] and "claim_token=" in stmts[3]
    assert stmts[4].startswith("UPDATE notification_devices")


async def test_delete_no_physical_delete_keeps_send_privacy_fence():
    d = device(send_locked_until=NOW + timedelta(seconds=120))
    db = session(result(D(**asdict(d))), result(), result())
    assert await SQLAlchemyNotificationRepository(db).unregister_device(
        d.customer_id, d.installation_id, NOW
    )
    stmts = statements(db)
    assert "customer_id =" in stmts[0] and "FOR UPDATE" in stmts[0]
    assert "send_locked_until=" not in stmts[1]
    assert not any(x.startswith("DELETE") for x in stmts)


async def test_cancel_only_unsent_preserves_sent_and_failed():
    db = session()
    await cancel_unsent(db, uuid4(), "DEVICE_CHANGED")
    query = db.execute.call_args.args[0]
    values = query.compile(dialect=postgresql.dialect()).params
    assert set(values["status_1"]) == {S.PENDING, S.PROCESSING}
    assert values["locked_until"] is None and values["claim_token"] is None


async def test_conflict_safe_message_and_no_token_from_db():
    db = session()
    db.commit.side_effect = IntegrityError(
        "private-test-token", {}, Exception("secret")
    )
    with pytest.raises(DeviceConflictError) as e:
        await SQLAlchemyNotificationRepository(db).commit()
    assert "secret" not in str(e.value) and "private" not in str(e.value)


@pytest.mark.parametrize(
    "model,mapper,factory",
    [
        (N, notification_domain, notification),
        (D, device_domain, device),
        (P, delivery_domain, delivery),
        (E, event_domain, event),
    ],
)
def test_all_mapper_roundtrips(model, mapper, factory):
    value = factory()
    assert mapper(model(**asdict(value))) == value


@pytest.mark.parametrize(
    "mapper", [notification_domain, device_domain, delivery_domain, event_domain]
)
def test_malformed_db_snapshot_safe_503(mapper):
    row = SimpleNamespace(
        model_dump=lambda: {"id": uuid4()},
        kind="bad",
        source_kind="bad",
        order_status=None,
        platform="bad",
        status="bad",
        mode="bad",
        event_type="bad",
        payment_status="bad",
    )
    with pytest.raises(NotificationDataError):
        mapper(row)


async def test_push_claim_empty_device_batch_skip_locked_closes_session():
    db = session(result(rows=[]))
    repo = SQLAlchemyPushRepository(lambda: db)
    assert await repo.claim(["test"], NOW, 10) == []
    assert "FOR UPDATE SKIP LOCKED" in statements(db)[0]
    assert "EXISTS" in statements(db)[0] and "send_locked_until" in statements(db)[0]
    db.__aexit__.assert_awaited_once()


async def test_push_claim_batched_queries_leases_fenced_and_session_closed():
    n, d = notification(), device()
    d = replace(d, customer_id=n.customer_id)
    p = delivery(n, d)
    db = session(
        result(rows=[D(**asdict(d))]),
        result(rows=[(P(**asdict(p)), N(**asdict(n)))]),
        result(),
        result(),
    )
    claims = await SQLAlchemyPushRepository(lambda: db).claim(["test"], NOW, 10)
    assert len(claims) == 1 and claims[0].delivery.attempt_count == 1
    assert claims[0].delivery.locked_until == NOW + timedelta(seconds=120)
    assert claims[0].delivery.claim_token is not None
    assert "FOR UPDATE OF notification_push_deliveries SKIP LOCKED" in statements(db)[1]
    assert db.execute.await_count == 4
    db.__aexit__.assert_awaited_once()


async def test_push_completion_invalid_token_retains_device_send_lease():
    n = notification()
    d = device(n.customer_id, send_locked_until=NOW + timedelta(seconds=120))
    from uuid import uuid4

    p = delivery(
        n,
        d,
        status=S.PROCESSING,
        attempt_count=1,
        locked_until=NOW + timedelta(seconds=120),
        claim_token=uuid4(),
    )
    claim = PushClaim(delivery=p, device=d, notification=n)
    db = session(
        result(D(**asdict(d))),
        result(P(**asdict(p))),
        result(),
        result(),
        result(),
        result(),
    )
    assert (
        await SQLAlchemyPushRepository(lambda: db).complete(
            claim, PushResult(kind=PushResultKind.INVALID_TOKEN), NOW
        )
        == S.FAILED
    )
    stmts = statements(db)
    assert "FOR UPDATE" in stmts[0] and "notification_devices" in stmts[0]
    assert "FOR UPDATE" in stmts[1] and "notification_push_deliveries" in stmts[1]
    assert not any("send_locked_until=" in x for x in stmts)
    assert "claim_token =" in stmts[2] and "status =" in stmts[2]


async def test_stream_reader_closes_session_before_return_and_no_writes():
    n = notification()
    db = session(result(1), result(rows=[N(**asdict(n))]))
    principal = SimpleNamespace(customer_id=n.customer_id)
    scope = SimpleNamespace(principal=principal, branch_id=None, credential="test")
    reader = SQLAlchemyStreamReader(lambda: db, AsyncMock(), lambda _: None)
    batch = await reader.read(scope, 0, 100, revalidate=False)
    assert batch.items == (n,)
    db.__aexit__.assert_awaited_once()
    assert all(s.startswith("SELECT") for s in statements(db))
    db.commit.assert_not_awaited()
