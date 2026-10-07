from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from uuid import uuid4

import pytest

from app.modules.notifications.domain.content import content
from app.modules.notifications.domain.models import (
    BIGINT_MAX,
    DevicePlatform,
    NotificationKind,
    NotificationRuleError,
    NotificationSource,
    PushDeliveryStatus,
    cursor,
    provider_code,
    push_token,
    retry_seconds,
    status_notification,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus
from tests.modules.notifications.fakes import NOW, delivery, device, notification


@pytest.mark.parametrize("mode", list(OrderMode))
@pytest.mark.parametrize("status", list(OrderStatus))
def test_rf53_exact_modalities_and_statuses(mode, status):
    expected = {
        (m, OrderStatus.PREPARING): NotificationKind.ORDER_PREPARING for m in OrderMode
    } | {
        (OrderMode.LOCAL, OrderStatus.READY): NotificationKind.ORDER_READY,
        (OrderMode.DELIVERY, OrderStatus.READY): NotificationKind.ORDER_READY,
        (
            OrderMode.PICKUP,
            OrderStatus.READY_FOR_PICKUP,
        ): NotificationKind.ORDER_READY_FOR_PICKUP,
        (
            OrderMode.DELIVERY,
            OrderStatus.OUT_FOR_DELIVERY,
        ): NotificationKind.ORDER_OUT_FOR_DELIVERY,
        (OrderMode.DELIVERY, OrderStatus.DELIVERED): NotificationKind.ORDER_DELIVERED,
    }
    assert status_notification(mode, status, OrderStatus.WAITING) == expected.get(
        (mode, status)
    )
    assert status_notification(mode, status, None) is None
    assert status_notification(mode, status, status) is None


@pytest.mark.parametrize("kind", list(NotificationKind))
def test_shared_content_safe_and_order_number_is_historical(kind):
    value = content(kind, 123)
    assert "#123" in value.body and value.title
    assert not any(
        x in value.body for x in ("token", "dirección", "Teléfono", "precio")
    )
    with pytest.raises(NotificationRuleError):
        content(kind, 0)


@pytest.mark.parametrize("value", [-1, BIGINT_MAX + 1, True, 1.2, "1", None])
def test_cursor_invalid(value):
    with pytest.raises(NotificationRuleError):
        cursor(value)


@pytest.mark.parametrize("value", [0, 1, BIGINT_MAX])
def test_cursor_valid(value):
    assert cursor(value) == value


@pytest.mark.parametrize("value", ["", "A", "two words", "../test", "a" * 33, None])
def test_invalid_provider(value):
    with pytest.raises(NotificationRuleError):
        provider_code(value)


@pytest.mark.parametrize("value", ["fcm", "test", "push-ios_2"])
def test_valid_provider(value):
    assert provider_code(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "a b", "a\nb", "a\rb", "a\x00b", "\u200bhidden", "é" * 1025, "a" * 2049, None],
)
def test_invalid_token(value):
    with pytest.raises(NotificationRuleError):
        push_token(value)


@pytest.mark.parametrize("value", ["test-only:abc_123", "a" * 2048, "é" * 1024])
def test_valid_opaque_token(value):
    assert push_token(value) == value


@pytest.mark.parametrize(
    "attempt,seconds", list(enumerate((30, 120, 600, 1800, 3600), 1))
)
def test_retry_intervals(attempt, seconds):
    assert retry_seconds(attempt) == seconds


@pytest.mark.parametrize("attempt", [0, 6, -1, True, "1", None])
def test_invalid_attempt_count(attempt):
    with pytest.raises(NotificationRuleError):
        retry_seconds(attempt)


@pytest.mark.parametrize(
    "change",
    [
        {"sequence_id": 0},
        {"order_number_snapshot": 0},
        {"kind": "ORDER_RECEIVED"},
        {"source_id": uuid4()},
        {"source_kind": NotificationSource.ORDER_STATUS_HISTORY},
        {"created_at": datetime(2026, 1, 1)},
        {"read_at": NOW.replace(year=2025)},
    ],
)
def test_notification_rejects_invalid_fact(change):
    with pytest.raises(NotificationRuleError):
        replace(notification(), **change)


@pytest.mark.parametrize("kind", list(NotificationKind))
def test_notification_provenance_unique_identity_not_latest_history(kind):
    n = notification(kind=kind)
    assert n.source_kind == (
        NotificationSource.ORDER
        if kind == NotificationKind.ORDER_RECEIVED
        else NotificationSource.DELIVERY_DELAY_INCIDENT
        if kind == NotificationKind.DELIVERY_DELAYED
        else NotificationSource.ORDER_STATUS_HISTORY
    )
    with pytest.raises(FrozenInstanceError):
        n.kind = NotificationKind.DELIVERY_DELAYED


@pytest.mark.parametrize(
    "change",
    [
        {"is_active": "true"},
        {"platform": "ANDROID"},
        {"generation": 0},
        {"generation": True},
        {"generation": 2147483648},
        {"created_at": datetime(2026, 1, 1)},
    ],
)
def test_device_validated(change):
    with pytest.raises(NotificationRuleError):
        replace(device(), **change)


@pytest.mark.parametrize(
    "change",
    [
        {"attempt_count": 6},
        {"attempt_count": -1},
        {"status": PushDeliveryStatus.PROCESSING},
        {"status": PushDeliveryStatus.SENT},
        {"locked_until": NOW},
        {"claim_token": uuid4()},
        {"sent_at": NOW},
        {"provider_message_id": "illegal-on-pending"},
        {"failure_code": "provider says private token"},
        {"next_attempt_at": datetime(2026, 1, 1)},
    ],
)
def test_delivery_invariants(change):
    with pytest.raises(NotificationRuleError):
        replace(delivery(), **change)


def test_secret_repr_never_shows_opaque_push_token():
    d = device(platform=DevicePlatform.IOS)
    assert d.push_token not in repr(d)
