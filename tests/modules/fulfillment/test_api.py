import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import OrderStatus
from tests.modules.fulfillment.fakes import change_order, delivery_order

ROUTES = [
    ("GET", "/pickup/due", None),
    ("POST", "/pickup/release-due", None),
    ("POST", "/pickup/orders/{order}/release", None),
    (
        "POST",
        "/pickup/orders/{order}/complete",
        {"customer_name": "María López", "customer_phone": "+51999888777"},
    ),
    ("GET", "/delivery/queue", None),
    ("PUT", "/delivery/orders/{order}/assignment", {"assigned_user_id": str(uuid4())}),
    ("DELETE", "/delivery/orders/{order}/assignment", None),
    ("POST", "/delivery/orders/{order}/dispatch", None),
    ("POST", "/delivery/orders/{order}/complete", None),
    ("POST", "/delivery/delays/detect", None),
    ("GET", "/delivery/delays", None),
    (
        "POST",
        "/delivery/delays/{incident}/approve",
        {"remediation_description": "Manual follow-up"},
    ),
    ("POST", "/delivery/delays/{incident}/reject", {}),
]


def request(api, route, headers=None, **changes):
    method, path, body = route
    path = path.format(order=api.setup.order.id, incident=uuid4())
    kwargs = {"headers": headers or {}}
    if body is not None:
        kwargs["json"] = body
    kwargs.update(changes)
    return api.client.request(method, api.base + path, **kwargs)


@pytest.mark.parametrize("route", ROUTES)
def test_every_endpoint_requires_jwt(api, route):
    assert request(api, route).status_code == 401


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("who", ["kitchen", "customer", "foreign", "guest"])
def test_every_endpoint_requires_branch_permission(api, route, who):
    assert request(api, route, api.headers(who)).status_code == 403
    assert (
        not api.setup.store.histories
        and not api.setup.store.assignments
        and not api.setup.store.incidents
    )


def test_revoked_permission_and_blocked_user_are_effective_immediately(api):
    api.setup.store.grants.clear()
    assert (
        api.client.get(api.base + "/pickup/due", headers=api.headers()).status_code
        == 403
    )
    api.auth.users[api.setup.admin.user_id] = replace(
        api.auth.users[api.setup.admin.user_id], account_status="BLOCKED"
    )
    assert (
        api.client.get(api.base + "/pickup/due", headers=api.headers()).status_code
        == 403
    )


def test_deleted_user_and_invalid_token_rejected(api):
    api.auth.users[api.setup.admin.user_id] = replace(
        api.auth.users[api.setup.admin.user_id], deleted_at=api.setup.now
    )
    assert (
        api.client.get(api.base + "/pickup/due", headers=api.headers()).status_code
        == 401
    )
    assert (
        api.client.get(
            api.base + "/pickup/due", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )


@pytest.mark.parametrize("route", ROUTES)
def test_unknown_query_fields_rejected_on_every_endpoint(api, route):
    response = request(
        api, route, api.headers(), params={"status_override": "PRIVATE_VALUE"}
    )
    assert response.status_code == 422 and "PRIVATE_VALUE" not in response.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "DELIVERED"),
        ("payment_status", "PAID"),
        ("total", "0.01"),
        ("delivery_fee", "0.00"),
        ("branch_id", str(uuid4())),
        ("confirmed_at", "2026-10-07T00:00:00Z"),
        ("estimated_delivery_at", "2026-10-07T00:00:00Z"),
        ("requested_pickup_at", "2026-10-07T00:00:00Z"),
        ("actor_user_id", str(uuid4())),
        ("address_line_snapshot", "PRIVATE_ADDRESS"),
    ],
)
@pytest.mark.parametrize("command", ["release", "assignment", "approve"])
def test_server_owned_fields_cannot_be_mass_assigned(api, field, value, command):
    if command == "release":
        url, method, body = api.pickup + "/release", "POST", {}
    elif command == "assignment":
        url, method, body = (
            api.delivery + "/assignment",
            "PUT",
            {"assigned_user_id": str(api.setup.kitchen.user_id)},
        )
    else:
        url, method, body = (
            api.base + "/delivery/delays/" + str(uuid4()) + "/approve",
            "POST",
            {"remediation_description": "manual"},
        )
    response = api.client.request(
        method, url, headers=api.headers(), json=body | {field: value}
    )
    assert response.status_code == 422 and value not in response.text
    assert (
        not api.setup.store.histories
        and not api.setup.store.assignments
        and not api.setup.store.incidents
    )


def test_pickup_read_release_and_retry(api):
    response = api.client.get(api.base + "/pickup/due", headers=api.headers())
    assert response.status_code == 200 and response.json()[0]["is_due"]
    assert "pickup_phone" not in response.text and not api.setup.store.histories
    first = api.client.post(api.pickup + "/release", headers=api.headers())
    retry = api.client.post(api.pickup + "/release", headers=api.headers(), json={})
    assert first.status_code == retry.status_code == 200
    assert first.json()["status"] == "WAITING" and first.json()["changed"]
    assert not retry.json()["changed"] and len(api.setup.store.histories) == 1


def test_bulk_endpoint_bounded_and_read_only_due_view(api):
    response = api.client.post(
        api.base + "/pickup/release-due",
        headers=api.headers(),
        params={"limit": 1},
        json={},
    )
    assert response.status_code == 200 and response.json()["released"] == 1
    assert api.client.get(api.base + "/pickup/due", headers=api.headers()).json() == []


def test_pickup_handover_no_identity_leak_or_persistence(api):
    change_order(api.setup, status=OrderStatus.READY_FOR_PICKUP)
    wrong = api.client.post(
        api.pickup + "/complete",
        headers=api.headers(),
        json={"customer_name": "Private wrong name", "customer_phone": "+51999888778"},
    )
    assert (
        wrong.status_code == 409
        and wrong.json()["error"]["code"] == "PICKUP_IDENTITY_MISMATCH"
    )
    assert "Private" not in wrong.text and "88778" not in wrong.text
    response = api.client.post(
        api.pickup + "/complete",
        headers=api.headers(),
        json={"customer_name": "MARÍA  LÓPEZ", "customer_phone": "+51 (999) 888-777"},
    )
    assert response.status_code == 200 and response.json()["status"] == "PICKED_UP"
    assert (
        "customer_name" not in response.text and "customer_phone" not in response.text
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"customer_name": "María López"},
        {"customer_name": "María\nLópez", "customer_phone": "+51999888777"},
        {"customer_name": "María López", "customer_phone": "777"},
        {
            "customer_name": "María López",
            "customer_phone": "+51999888777",
            "force": True,
        },
    ],
)
def test_invalid_handover_input_is_422_and_no_write(api, body):
    change_order(api.setup, status=OrderStatus.READY_FOR_PICKUP)
    response = api.client.post(
        api.pickup + "/complete", headers=api.headers(), json=body
    )
    assert response.status_code == 422 and not api.setup.store.histories


def test_delivery_queue_and_assignment_dispatch_completion_end_to_end(api):
    order = delivery_order(api.setup)
    queue = api.client.get(api.base + "/delivery/queue", headers=api.headers())
    assert queue.status_code == 200
    assert queue.json()[0]["address_line_snapshot"] == order.address_line_snapshot
    for hidden in (
        "password",
        "provider_reference",
        "idempotency_key",
        "subtotal",
        "total",
        "customer_id",
    ):
        assert hidden not in queue.text
    assigned = api.client.put(
        api.delivery + "/assignment",
        headers=api.headers(),
        json={"assigned_user_id": str(api.setup.kitchen.user_id)},
    )
    assert assigned.status_code == 200
    assert (
        api.client.get(api.base + "/delivery/queue", headers=api.headers()).json()[0][
            "active_assignment"
        ]["id"]
        == assigned.json()["id"]
    )
    dispatched = api.client.post(api.delivery + "/dispatch", headers=api.headers())
    assert (
        dispatched.status_code == 200
        and dispatched.json()["status"] == "OUT_FOR_DELIVERY"
    )
    delivered = api.client.post(api.delivery + "/complete", headers=api.headers())
    assert delivered.status_code == 200 and delivered.json()["status"] == "DELIVERED"
    assert (
        api.client.get(api.base + "/delivery/queue", headers=api.headers()).json() == []
    )
    assert len(api.setup.store.histories) == 2


def test_unassignment_endpoint_204_idempotent_preserves_history(api):
    delivery_order(api.setup)
    api.client.put(
        api.delivery + "/assignment",
        headers=api.headers(),
        json={"assigned_user_id": str(api.setup.kitchen.user_id)},
    )
    for _ in range(2):
        response = api.client.delete(
            api.delivery + "/assignment", headers=api.headers()
        )
        assert response.status_code == 204 and response.content == b""
    assert (
        len(api.setup.store.assignments) == 1
        and not next(iter(api.setup.store.assignments.values())).active
    )


def test_invalid_assignee_safe_conflict(api):
    delivery_order(api.setup)
    response = api.client.put(
        api.delivery + "/assignment",
        headers=api.headers(),
        json={"assigned_user_id": str(uuid4())},
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "DELIVERY_ASSIGNEE_INVALID"
    )


def test_delay_detection_list_human_approval_and_conflict(api):
    original = delivery_order(api.setup)
    assert (
        api.client.get(api.base + "/delivery/delays", headers=api.headers()).json()
        == []
    )
    response = api.client.post(
        api.base + "/delivery/delays/detect", headers=api.headers()
    )
    assert response.status_code == 200 and response.json()["new_incidents"] == 1
    rows = api.client.get(
        api.base + "/delivery/delays", headers=api.headers(), params={"status": "OPEN"}
    ).json()
    assert len(rows) == 1 and rows[0]["decision_status"] == "OPEN"
    url = api.base + "/delivery/delays/" + rows[0]["id"]
    body = {
        "customer_responsibility": True,
        "evaluation_note": "Customer caused delay",
        "remediation_description": "Manual review only",
    }
    approved = api.client.post(url + "/approve", headers=api.headers(), json=body)
    assert (
        approved.status_code == 200
        and approved.json()["customer_responsibility"] is True
    )
    assert (
        api.client.post(url + "/approve", headers=api.headers(), json=body).json()
        == approved.json()
    )
    assert (
        api.client.post(url + "/reject", headers=api.headers(), json={}).status_code
        == 409
    )
    assert (
        api.setup.store.orders[original.id] == original
        and not api.setup.store.histories
    )


@pytest.mark.parametrize("value", [0, 1, "true", "false", "yes", [], {}])
def test_responsibility_strict_boolean_not_inferred(api, value):
    response = api.client.post(
        api.base + "/delivery/delays/" + str(uuid4()) + "/reject",
        headers=api.headers(),
        json={"customer_responsibility": value},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"remediation_description": " "},
        {"remediation_description": "x" * 2001},
        {"remediation_description": "Private\x00note"},
        {"remediation_description": "valid", "refund_amount": "10.00"},
    ],
)
def test_approval_description_required_and_no_financial_remediation(api, body):
    response = api.client.post(
        api.base + "/delivery/delays/" + str(uuid4()) + "/approve",
        headers=api.headers(),
        json=body,
    )
    assert response.status_code == 422


def test_rejection_has_no_remediation_description(api):
    response = api.client.post(
        api.base + "/delivery/delays/" + str(uuid4()) + "/reject",
        headers=api.headers(),
        json={"remediation_description": "disallowed"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "query", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": 2147483648}]
)
def test_list_pagination_validation(api, query):
    assert (
        api.client.get(
            api.base + "/pickup/due", headers=api.headers(), params=query
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "status", ["DELIVERED", "CANCELLED", "PICKED_UP", "SCHEDULED", "PAID"]
)
def test_delivery_queue_cannot_select_non_operational_states(api, status):
    assert (
        api.client.get(
            api.base + "/delivery/queue",
            headers=api.headers(),
            params={"status": status},
        ).status_code
        == 422
    )


def test_order_and_incident_of_another_authorized_branch_are_hidden(api):
    foreign = uuid4()
    for permission in ("FULFILLMENT_MANAGE", "DELIVERY_DELAY_REVIEW"):
        api.setup.store.grants.add((api.setup.admin.user_id, foreign, permission))
    foreign_base = api.base.replace(str(api.setup.branch), str(foreign))
    assert (
        api.client.post(
            foreign_base + "/pickup/orders/" + str(api.setup.order.id) + "/release",
            headers=api.headers(),
        ).status_code
        == 404
    )
    delivery_order(api.setup)
    asyncio.run(
        api.setup.service.detect_delivery_delays(api.setup.admin, api.setup.branch)
    )
    incident = next(iter(api.setup.store.incidents.values()))
    assert (
        api.client.post(
            foreign_base + "/delivery/delays/" + str(incident.id) + "/reject",
            headers=api.headers(),
            json={},
        ).status_code
        == 404
    )


def test_openapi_contains_thirteen_operations_with_standard_errors(api):
    paths = {
        p: value
        for p, value in api.client.get("/openapi.json").json()["paths"].items()
        if "/admin/fulfillment/" in p
    }
    assert len(paths) == 12
    operations = [
        operation
        for value in paths.values()
        for method, operation in value.items()
        if method in {"get", "post", "put", "delete"}
    ]
    assert len(operations) == 13
    assert all(
        {"401", "403", "404", "409", "422", "503"} <= set(operation["responses"])
        for operation in operations
    )
    assert not any("/customer/" in p or "/status" in p for p in paths)


def test_permission_separation_view_does_not_grant_assignment_or_review(api):
    api.setup.store.grants = {
        (api.setup.admin.user_id, api.setup.branch, "FULFILLMENT_VIEW")
    }
    assert (
        api.client.get(api.base + "/delivery/queue", headers=api.headers()).status_code
        == 200
    )
    assert (
        api.client.post(
            api.base + "/delivery/delays/detect", headers=api.headers()
        ).status_code
        == 403
    )
    assert (
        api.client.put(
            api.delivery + "/assignment",
            headers=api.headers(),
            json={"assigned_user_id": str(api.setup.kitchen.user_id)},
        ).status_code
        == 403
    )
