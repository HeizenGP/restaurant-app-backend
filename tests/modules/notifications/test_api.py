from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.notifications.application.dtos import AdminOrderSnapshot
from app.modules.notifications.infrastructure.push_gateway import (
    ConfiguredPushGatewayRegistry,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus
from tests.modules.notifications.fakes import NOW, enqueue, event, notification


@pytest.mark.parametrize("who", ["customer", "guest"])
def test_inapp_owned_and_safe_read_api(api, who):
    p = getattr(api.setup, who)
    n = notification(p.customer_id, api.setup.branch)
    enqueue(api.setup.store, n)
    foreign = notification(api.setup.foreign.customer_id, sequence=99)
    enqueue(api.setup.store, foreign)
    response = api.client.get(api.base, headers=api.headers(who))
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1 and body["latest_sequence_id"] == 1
    item = body["items"][0]
    assert item["order_number"] == 123 and "#123" in item["body"]
    assert not item["is_read"]
    assert not {"customer_id", "source_id", "source_kind", "push_token"} & item.keys()
    path = api.base + "/" + str(n.id) + "/read"
    first = api.client.post(path, headers=api.headers(who))
    assert first.status_code == 200 and first.json()["is_read"]
    assert api.client.post(path, headers=api.headers(who)).json() == first.json()
    assert api.client.get(
        api.base + "/unread-count", headers=api.headers(who)
    ).json() == {"unread_count": 0}
    assert api.client.post(
        api.base + "/read-all", headers=api.headers(who), json={}
    ).json() == {"marked_count": 0}


def test_idor_and_server_owned_fields(api):
    n = notification(api.setup.foreign.customer_id)
    enqueue(api.setup.store, n)
    for identifier in [n.id, uuid4()]:
        response = api.client.post(
            api.base + "/" + str(identifier) + "/read", headers=api.headers()
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOTIFICATION_NOT_FOUND"
    response = api.client.post(
        api.base + "/read-all", headers=api.headers(), json={"read_at": "injected"}
    )
    assert response.status_code == 422


def test_device_register_rotate_delete_safe(api):
    installation = str(uuid4())
    path = api.base + "/devices/" + installation
    body = {
        "platform": "ANDROID",
        "provider_code": "test",
        "push_token": "test-only-token",
    }
    first = api.client.put(path, headers=api.headers(), json=body)
    assert first.status_code == 200
    assert "test-only-token" not in first.text and "push_token" not in first.text
    again = api.client.put(path, headers=api.headers(), json=body)
    assert again.json()["id"] == first.json()["id"]
    assert api.client.delete(path, headers=api.headers("foreign")).status_code == 404
    assert api.client.delete(path, headers=api.headers()).status_code == 204
    assert api.client.delete(path, headers=api.headers()).status_code == 204
    api.setup.service.registry = ConfiguredPushGatewayRegistry()
    assert api.client.put(path, headers=api.headers(), json=body).status_code == 503


@pytest.mark.parametrize(
    "patch",
    [
        {"customer_id": str(uuid4())},
        {"platform": "DESKTOP"},
        {"provider_code": "FCM"},
        {"push_token": "contains space"},
        {"push_token": "x" * 2049},
        {"push_token": "a\nb"},
        {"push_token": "\u200btoken"},
        {"token": "secret"},
    ],
)
def test_device_validation_redacts_input(api, patch):
    body = {
        "platform": "ANDROID",
        "provider_code": "test",
        "push_token": "safe-test",
    } | patch
    response = api.client.put(
        api.base + "/devices/" + str(uuid4()), headers=api.headers(), json=body
    )
    assert response.status_code == 422
    assert "safe-test" not in response.text and "contains space" not in response.text


@pytest.mark.parametrize(
    "path", ["", "/unread-count", "/read-all", "/stream", "/devices/{id}", "/{id}/read"]
)
def test_bearer_required_all_customer_operations(api, path):
    path = api.base + path.format(id=uuid4())
    if path.endswith("/read-all") or path.endswith("/read"):
        response = api.client.post(path)
    elif "/devices/" in path:
        response = api.client.delete(path)
    else:
        response = api.client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=101",
        "?before_sequence_id=-1",
        "?before_sequence_id=9223372036854775808",
        "?customer_id=other",
    ],
)
def test_list_query_bounded_and_forbids_owner_injection(api, query):
    assert api.client.get(api.base + query, headers=api.headers()).status_code == 422


@pytest.mark.parametrize("who", ["customer", "guest", "foreign", "kitchen"])
def test_admin_realtime_permission(api, who):
    assert api.client.get(api.admin, headers=api.headers(who)).status_code == 403
    assert (
        api.client.get(api.admin + "/events", headers=api.headers(who)).status_code
        == 403
    )


def test_snapshot_minimal_scope_active_and_explicit_terminal(api):
    s = api.setup
    row = AdminOrderSnapshot(
        order_id=uuid4(),
        order_number=1,
        mode=OrderMode.LOCAL,
        status=OrderStatus.WAITING,
        payment_status=PaymentStatus.PENDING,
        customer_name_snapshot="Historical",
        created_at=NOW,
        confirmed_at=None,
        updated_at=NOW,
    )
    s.store.snapshots += [
        (s.branch, row),
        (
            s.branch,
            replace(
                row, order_id=uuid4(), order_number=2, status=OrderStatus.CANCELLED
            ),
        ),
        (s.other_branch, replace(row, order_id=uuid4(), order_number=3)),
    ]
    s.store.events[1] = event(s.branch)
    response = api.client.get(api.admin, headers=api.headers("admin"))
    assert response.status_code == 200
    body = response.json()
    assert body["latest_event_id"] == 1 and len(body["orders"]) == 1
    assert set(body["orders"][0]) == {
        "order_id",
        "order_number",
        "mode",
        "status",
        "payment_status",
        "customer_name_snapshot",
        "created_at",
        "confirmed_at",
        "updated_at",
    }
    assert (
        api.client.get(
            api.admin + "?status=CANCELLED", headers=api.headers("admin")
        ).json()["orders"][0]["order_number"]
        == 2
    )
    assert (
        api.client.get(
            api.admin.replace(str(s.branch), str(s.other_branch)),
            headers=api.headers("admin"),
        ).status_code
        == 403
    )


def test_admin_events_minimal_and_cursor(api):
    s = api.setup
    s.store.events[1] = event(s.branch)
    s.store.events[3] = event(s.branch, 3)
    s.store.events[2] = event(s.other_branch, 2)
    response = api.client.get(
        api.admin + "/events?after_id=1", headers=api.headers("admin")
    )
    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == [3]
    assert "customer_name" not in response.text
    assert "source_reference_id" not in response.text


@pytest.mark.parametrize(
    "suffix,who",
    [
        ("/api/v1/notifications/stream", "customer"),
        ("/api/v1/notifications/stream", "guest"),
        ("admin", "admin"),
        ("kitchen", "kitchen"),
        ("kitchen", "admin"),
    ],
)
def test_sse_auth_headers_ready_resume_and_safe_content(api, suffix, who):
    s = api.setup
    n = notification(getattr(s, who).customer_id or s.customer.customer_id, s.branch)
    enqueue(s.store, n)
    s.store.events[1] = event(s.branch)
    path = (
        api.admin + "/stream"
        if suffix == "admin"
        else (api.kitchen if suffix == "kitchen" else suffix)
    )
    response = api.client.get(path + "?after_id=0", headers=api.headers(who))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert "id: 0\nevent: ready" in response.text
    assert "id: 1" in response.text
    assert s.repo.released and api.reader.calls[0][-1] is True
    assert "push_token" not in response.text and "source_id" not in response.text


def test_header_cursor_explicit_query_wins_and_no_url_tokens(api):
    n = notification(api.setup.customer.customer_id, sequence=2)
    enqueue(api.setup.store, n)
    path = api.base + "/stream"
    response = api.client.get(path, headers=api.headers(**{"Last-Event-ID": "2"}))
    assert response.status_code == 200 and "notification.created" not in response.text
    response = api.client.get(
        path + "?after_id=0", headers=api.headers(**{"Last-Event-ID": "not-used"})
    )
    assert response.status_code == 200 and "notification.created" in response.text
    assert (
        api.client.get(
            path + "?access_token=must-not-be-accepted", headers=api.headers()
        ).status_code
        == 422
    )


@pytest.mark.parametrize("cursor", ["-1", "1.5", " 1", "9223372036854775808", "abc"])
def test_invalid_sse_header_before_response(api, cursor):
    response = api.client.get(
        api.base + "/stream", headers=api.headers(**{"Last-Event-ID": cursor})
    )
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"


def test_future_cursor_and_kitchen_separation(api):
    assert (
        api.client.get(
            api.base + "/stream?after_id=999", headers=api.headers()
        ).status_code
        == 422
    )
    assert (
        api.client.get(api.kitchen, headers=api.headers("customer")).status_code == 403
    )
    assert (
        api.client.get(
            api.admin + "/stream", headers=api.headers("kitchen")
        ).status_code
        == 403
    )


def test_openapi_exact_phase9_operations_and_sse_documented(api):
    schema = api.client.get("/openapi.json").json()
    paths = {
        p: m
        for p, m in schema["paths"].items()
        if "/notifications" in p
        or "/admin/realtime/" in p
        or p.endswith("/orders/stream")
    }
    assert len(paths) == 10 and sum(len(m) for m in paths.values()) == 11
    for path, operations in paths.items():
        for operation in operations.values():
            assert "security" in operation
            if path.endswith("/stream"):
                assert "text/event-stream" in operation["responses"]["200"]["content"]
    assert (
        "push_token"
        not in schema["components"]["schemas"]["DeviceResponse"]["properties"]
    )
