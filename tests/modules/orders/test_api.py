import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from app.shared.application.exceptions import DependencyUnavailableError


def test_guest_create_read_and_idempotent_replay(api):
    first = api.create()
    assert first.status_code == 201
    data = first.json()
    assert data["status"] == "PENDING_CASH_CONFIRMATION"
    assert data["payment_status"] == "PENDING" and data["subtotal"] == "20.00"
    assert data["local_details"]["table_label"] == "Mesa Test"
    assert data["items"][0]["product_name_snapshot"] == "Aeropuerto"
    assert "idempotency_key" not in data and "request_fingerprint" not in data
    assert api.create().json()["id"] == data["id"]
    detail = api.client.get("/api/v1/orders/" + data["id"], headers=api.headers())
    assert detail.status_code == 200 and detail.json() == data


def test_registered_create_and_staff_without_customer_rejected(api):
    asyncio.run(api.setup.prepare(api.setup.cart.registered))
    assert api.create("registered").status_code == 201
    assert api.create("staff").status_code == 401


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "order_number",
        "customer_id",
        "branch_id",
        "subtotal",
        "charges_total",
        "discount_total",
        "delivery_fee",
        "total",
        "unit_price",
        "payment_status",
        "status",
        "created_at",
        "updated_at",
    ],
)
def test_create_rejects_frontend_owned_identity_status_and_prices(api, field):
    response = api.create(body=api.local_body(**{field: "untrusted"}))
    assert response.status_code == 422
    assert not api.setup.store.orders
    assert "untrusted" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "OTHER"},
        {"mode": "LOCAL", "payment_method": "CASH"},
        {"mode": "DELIVERY"},
        {"mode": "PICKUP", "requested_pickup_at": "2026-10-07T19:00:00"},
        {
            "mode": "PICKUP",
            "requested_pickup_at": "2026-10-07T19:00:00-05:00",
            "payment_method": "CASH",
        },
        {
            "mode": "DELIVERY",
            "address_id": str(uuid4()),
            "table_qr_token": str(uuid4()),
        },
        {
            "mode": "LOCAL",
            "table_qr_token": str(uuid4()),
            "payment_method": "CASH",
            "address_id": str(uuid4()),
        },
    ],
)
def test_discriminated_union_forbids_wrong_mode_fields(api, body):
    assert api.create(body=body).status_code == 422


@pytest.mark.parametrize("key", [None, "", "has spaces", "a" * 129])
def test_idempotency_key_is_required_and_bounded(api, key):
    headers = api.headers()
    if key is None:
        headers.pop("Idempotency-Key")
    else:
        headers["Idempotency-Key"] = key
    response = api.client.post("/api/v1/orders", headers=headers, json=api.local_body())
    assert response.status_code == 422 and not api.setup.store.orders


def test_different_body_same_key_returns_409(api):
    assert api.create().status_code == 201
    conflict = api.create(body=api.local_body(payment_method="ONLINE"))
    assert (
        conflict.status_code == 409
        and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    )


def test_pickup_and_delivery_request_contracts(api):
    pickup = api.create(
        body={
            "mode": "PICKUP",
            "requested_pickup_at": (api.setup.now + timedelta(hours=2)).isoformat(),
        }
    )
    assert pickup.status_code == 201
    data = pickup.json()
    assert (
        data["payment_method_type"] == "ONLINE" and data["status"] == "PENDING_PAYMENT"
    )
    assert data["pickup_details"]["calculated_kitchen_release_at"]
    assert data["pickup_details"]["pickup_phone"] == "+51900000111"
    asyncio.run(api.setup.prepare())
    delivery = api.create(
        key="delivery",
        body={"mode": "DELIVERY", "address_id": str(api.setup.address.id)},
    )
    assert delivery.status_code == 201 and delivery.json()["delivery_fee"] == "0.00"
    assert delivery.json()["delivery_details"]["estimated_delivery_at"]


def test_owner_scope_and_pagination(api):
    order = api.create().json()
    foreign = api.client.get(
        "/api/v1/orders/" + order["id"], headers=api.headers("other")
    )
    missing = api.client.get(
        "/api/v1/orders/" + str(uuid4()), headers=api.headers("other")
    )
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert api.client.get("/api/v1/orders", headers=api.headers("other")).json() == []
    page = api.client.get("/api/v1/orders?limit=1&offset=0", headers=api.headers())
    assert page.status_code == 200 and len(page.json()) == 1


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "customer_id=spoof", "status=PAID"]
)
def test_list_bounds_and_unknown_query_rejected(api, query):
    assert (
        api.client.get("/api/v1/orders?" + query, headers=api.headers()).status_code
        == 422
    )


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/v1/orders", {"mode": "DELIVERY", "address_id": str(uuid4())}),
        ("get", "/api/v1/orders", None),
        ("get", "/api/v1/orders/" + str(uuid4()), None),
        ("post", "/api/v1/admin/orders/" + str(uuid4()) + "/confirm-cash-release", {}),
    ],
)
def test_no_jwt_is_401(api, method, path, body):
    assert (
        getattr(api.client, method)(
            path, **({"json": body} if body is not None else {})
        ).status_code
        == 401
    )


def test_invalid_and_blocked_token_is_401(api):
    response = api.client.get(
        "/api/v1/orders", headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401
    user_id = api.setup.cart.registered.user_id
    api.auth.users[user_id] = replace(api.auth.users[user_id], account_status="BLOCKED")
    assert api.create("registered").status_code == 403


def test_cash_release_preserves_payment_pending(api):
    order = api.create().json()
    path = "/api/v1/admin/orders/" + order["id"] + "/confirm-cash-release"
    released = api.client.post(path, headers=api.headers("admin"), json={})
    assert released.status_code == 200
    assert (
        released.json()["status"] == "WAITING"
        and released.json()["payment_status"] == "PENDING"
    )
    assert len(released.json()["history"]) == 2
    assert (
        api.client.post(path, headers=api.headers("admin"), json={}).status_code == 409
    )


@pytest.mark.parametrize("who", ["guest", "registered", "foreign_admin", "staff"])
def test_cash_release_and_settings_require_live_branch_grant(api, who):
    order = api.create().json()
    path = "/api/v1/admin/orders/" + order["id"] + "/confirm-cash-release"
    assert api.client.post(path, headers=api.headers(who), json={}).status_code == 403
    assert (
        api.client.get(
            api.admin_path + "/settings", headers=api.headers(who)
        ).status_code
        == 403
    )


def test_admin_settings_patch_and_cross_branch_protection(api):
    path = api.admin_path + "/settings"
    assert (
        api.client.get(path, headers=api.headers("admin")).json()[
            "default_prep_minutes"
        ]
        == 20
    )
    response = api.client.patch(
        path,
        headers=api.headers("admin"),
        json={"default_prep_minutes": 30, "delivery_minimum_order": "25.50"},
    )
    assert (
        response.status_code == 200
        and response.json()["delivery_minimum_order"] == "25.50"
    )
    other = path.replace(str(api.setup.cart.branch), str(api.setup.cart.other_branch))
    assert (
        api.client.patch(
            other, headers=api.headers("admin"), json={"default_prep_minutes": 10}
        ).status_code
        == 403
    )
    api.setup.store.grants.clear()
    assert api.client.get(path, headers=api.headers("admin")).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"default_prep_minutes": 0},
        {"pickup_buffer_minutes": -1},
        {"default_prep_minutes": True},
        {"timezone": "Invalid/Zone"},
        {"delivery_minimum_order": "-1"},
        {"cash_payment_requires_confirmation": 1},
        {"branch_id": str(uuid4())},
        {"timezone": None},
    ],
)
def test_admin_invalid_settings_rejected(api, body):
    response = api.client.patch(
        api.admin_path + "/settings", headers=api.headers("admin"), json=body
    )
    assert response.status_code == 422


def test_tables_admin_crud_rotate_and_logical_delete(api):
    path = api.admin_path + "/tables"
    table = api.client.post(
        path, headers=api.headers("admin"), json={"label": "Mesa Patio"}
    )
    assert table.status_code == 201
    data = table.json()
    rotated = api.client.patch(
        path + "/" + data["id"],
        headers=api.headers("admin"),
        json={"rotate_qr_token": True},
    )
    assert rotated.status_code == 200 and rotated.json()["qr_token"] != data["qr_token"]
    deleted = api.client.delete(path + "/" + data["id"], headers=api.headers("admin"))
    assert deleted.status_code == 204 and deleted.content == b""
    listed = api.client.get(path, headers=api.headers("admin")).json()
    assert not next(table for table in listed if table["id"] == data["id"])["is_active"]


def test_delivery_zones_admin_crud_and_global_seed_protection(api):
    path = api.admin_path + "/delivery-zones"
    data = api.client.post(
        path,
        headers=api.headers("admin"),
        json={
            "name": "Juan Guerra",
            "district": " Juan Guerra ",
            "delivery_fee": "8.00",
        },
    )
    assert data.status_code == 201 and data.json()["district"] == "Juan Guerra"
    zone_id = data.json()["id"]
    changed = api.client.patch(
        path + "/" + zone_id,
        headers=api.headers("admin"),
        json={"estimated_travel_minutes": 30},
    )
    assert changed.status_code == 200
    assert (
        api.client.delete(
            path + "/" + zone_id, headers=api.headers("admin")
        ).status_code
        == 204
    )
    global_id = str(
        next(
            zone.id for zone in api.setup.store.zones.values() if zone.branch_id is None
        )
    )
    assert (
        api.client.patch(
            path + "/" + global_id,
            headers=api.headers("admin"),
            json={"delivery_fee": "5.00"},
        ).status_code
        == 404
    )


def test_dependency_failure_is_safe_503(api, monkeypatch):
    async def unavailable(*args):
        raise DependencyUnavailableError("Order database is unavailable")

    monkeypatch.setattr(api.setup.service, "create", unavailable)
    response = api.create()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_openapi_has_discriminator_and_no_payment_or_kitchen_write(api):
    schema = api.client.get("/openapi.json").json()
    request = schema["paths"]["/api/v1/orders"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert (
        request["discriminator"]["propertyName"] == "mode"
        and len(request["oneOf"]) == 3
    )
    paths = [path for path in schema["paths"] if "orders" in path]
    assert len(paths) == 8
    assert sum(len(schema["paths"][path]) for path in paths) == 14
    assert not any(
        "mark-paid" in path or "kitchen" in path or "recalculate" in path
        for path in paths
    )
