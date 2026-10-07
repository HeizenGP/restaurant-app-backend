import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import OrderStatus
from app.modules.payments.infrastructure.gateway import UnconfiguredOnlinePaymentGateway
from tests.modules.payments.fakes import (
    cash_order,
    change_order,
    initiated,
    signed_event,
)


def start(api, who="customer", key="test", **kwargs):
    return api.client.post(
        api.base + "/online", headers=api.headers(who, key=key), **kwargs
    )


def test_online_endpoint_uses_historical_money_and_safe_response(api):
    response = start(api)
    assert response.status_code == 200
    result = response.json()
    assert (
        result["payment"]["amount"] == "32.50"
        and result["payment"]["currency_code"] == "PEN"
    )
    assert (
        result["payment"]["status"] == "PROCESSING"
        and result["attempt"]["status"] == "PROCESSING"
    )
    assert result["client_action"]["kind"] == "REDIRECT"
    assert api.setup.db.orders[api.setup.order.id].status == OrderStatus.PENDING_PAYMENT
    text = response.text.lower()
    for hidden in (
        "provider_reference",
        "idempotency_key",
        "payload_hash",
        "password",
        "authorization",
        "recipient",
        "phone",
        "address",
        "client_action_value",
    ):
        assert hidden not in text


@pytest.mark.parametrize("path", ["read", "online", "cash"])
def test_missing_jwt_rejected(api, path):
    url = (
        api.base
        if path == "read"
        else api.base + "/online"
        if path == "online"
        else api.cash
    )
    response = (
        api.client.get(url)
        if path == "read"
        else api.client.post(url, headers={"Idempotency-Key": "test"})
    )
    assert response.status_code == 401 and not api.setup.db.payments


@pytest.mark.parametrize("who", ["admin", "kitchen"])
def test_non_customer_principal_cannot_start_online(api, who):
    assert start(api, who).status_code == 401


@pytest.mark.parametrize("who", ["foreign", "guest"])
def test_other_customer_order_hidden(api, who):
    assert start(api, who).status_code == 404
    assert api.client.get(api.base, headers=api.headers(who)).status_code == 404
    assert not api.setup.gateway.calls


def test_guest_can_initiate_own_order(api):
    change_order(api.setup, customer_id=api.setup.guest.customer_id)
    assert start(api, "guest").status_code == 200


def test_blocked_registered_user_not_allowed(api):
    uid = api.setup.customer.user_id
    api.auth.users[uid] = replace(api.auth.users[uid], account_status="BLOCKED")
    assert start(api).status_code == 403 and not api.setup.db.payments


@pytest.mark.parametrize("key", [None, "", "bad key", "a" * 129, "bad/route"])
def test_idempotency_header_is_required_and_validated(api, key):
    assert start(api, key=key).status_code == 422
    assert not api.setup.db.payments


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "0.01"),
        ("currency_code", "USD"),
        ("status", "PAID"),
        ("payment_status", "PAID"),
        ("order_id", str(uuid4())),
        ("customer_id", str(uuid4())),
        ("branch_id", str(uuid4())),
        ("provider_code", "test_gateway"),
        ("provider_reference", "private-provider-reference-123"),
        ("card_number", "4111111111111111"),
        ("cvv", "123"),
        ("paid_at", "2026-10-07T00:00:00Z"),
    ],
)
@pytest.mark.parametrize("location", ["body", "query"])
def test_customer_cannot_mass_assign_financial_fields(api, field, value, location):
    kwargs = (
        {"json": {field: value}} if location == "body" else {"params": {field: value}}
    )
    response = start(api, **kwargs)
    assert response.status_code == 422
    assert not api.setup.db.payments
    assert value not in response.text


def test_online_body_can_be_absent_or_empty(api):
    one = start(api)
    two = start(api, json={})
    assert one.status_code == two.status_code == 200
    assert one.json() == two.json() and len(api.setup.gateway.calls) == 1


def test_same_key_and_other_key_conflict(api):
    first = start(api)
    assert start(api).json() == first.json()
    response = start(api, key="new")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PAYMENT_IDEMPOTENCY_CONFLICT"


def test_get_payment_has_no_client_action_or_provider_reference(api):
    assert api.client.get(api.base, headers=api.headers()).status_code == 404
    start(api)
    read = api.client.get(api.base, headers=api.headers())
    assert (
        read.status_code == 200
        and "client_action" not in read.text
        and "ref_" not in read.text
    )
    assert len(api.setup.gateway.calls) == 1


def test_cash_endpoint_paid_but_does_not_release(api):
    cash_order(api.setup)
    first = api.client.post(api.cash, headers=api.headers("admin"))
    second = api.client.post(api.cash, headers=api.headers("admin"), json={})
    assert (
        first.status_code == second.status_code == 200 and first.json() == second.json()
    )
    assert first.json()["status"] == "PAID"
    assert (
        api.setup.db.orders[api.setup.order.id].status
        == OrderStatus.PENDING_CASH_CONFIRMATION
    )
    assert not api.setup.db.order_histories and len(api.setup.db.histories) == 2


@pytest.mark.parametrize("who", ["guest", "customer", "foreign", "kitchen"])
def test_cash_denies_without_branch_permission(api, who):
    cash_order(api.setup)
    assert api.client.post(api.cash, headers=api.headers(who)).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"amount_received": "100.00"},
        {"status": "PAID"},
        {"payment_status": "PAID"},
        {"branch_id": str(uuid4())},
    ],
)
def test_cash_command_has_no_financial_inputs(api, body):
    cash_order(api.setup)
    assert (
        api.client.post(api.cash, headers=api.headers("admin"), json=body).status_code
        == 422
    )
    assert not api.setup.db.payments


def test_cash_revoked_permission_effective_immediately(api):
    cash_order(api.setup)
    api.setup.authz.grants.clear()
    assert api.client.post(api.cash, headers=api.headers("admin")).status_code == 403


def test_online_unconfigured_returns_explicit_503_no_fake_payment(api):
    api.setup.service.gateway = UnconfiguredOnlinePaymentGateway()
    response = start(api)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PAYMENT_PROVIDER_UNAVAILABLE"
    assert not api.setup.db.payments and not api.setup.db.attempts


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer fake"}, {"x-test-signature": "bad"}]
)
def test_public_paid_json_never_authenticates_webhook(api, headers):
    response = api.client.post(
        "/api/v1/payments/webhooks/test_gateway",
        content=b'{"status":"PAID"}',
        headers=headers,
    )
    assert response.status_code == 401 and not api.setup.db.events


def test_authenticated_webhook_without_jwt_confirms_and_deduplicates(api):
    result = asyncio.run(initiated(api.setup))
    body, headers = signed_event(result.attempt)
    first = api.client.post(
        "/api/v1/payments/webhooks/test_gateway", content=body, headers=headers
    )
    second = api.client.post(
        "/api/v1/payments/webhooks/test_gateway", content=body, headers=headers
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == {"status": "acknowledged"} and first.json() == second.json()
    assert len(api.setup.db.events) == 1 and len(api.setup.db.order_histories) == 1
    assert api.setup.db.orders[api.setup.order.id].status == OrderStatus.WAITING


def test_verified_amount_mismatch_acknowledged_without_payment(api):
    result = asyncio.run(initiated(api.setup))
    body, headers = signed_event(result.attempt, amount="1.00")
    response = api.client.post(
        "/api/v1/payments/webhooks/test_gateway", content=body, headers=headers
    )
    assert response.status_code == 200 and response.json() == {"status": "acknowledged"}
    assert api.setup.db.orders[api.setup.order.id].status == OrderStatus.PENDING_PAYMENT


def test_valid_signature_invalid_event_returns_safe_422(api):
    import hashlib
    import hmac

    from tests.modules.payments.fakes import TEST_SECRET

    body = b'{"private":"secret-provider-payload"}'
    headers = {
        "x-test-signature": hmac.new(TEST_SECRET, body, hashlib.sha256).hexdigest()
    }
    response = api.client.post(
        "/api/v1/payments/webhooks/test_gateway", content=body, headers=headers
    )
    assert (
        response.status_code == 422 and "secret-provider-payload" not in response.text
    )
    assert not api.setup.db.events


def test_webhook_size_is_bounded_before_verification(api):
    response = api.client.post(
        "/api/v1/payments/webhooks/test_gateway", content=b"x" * 65537
    )
    assert response.status_code == 422 and api.setup.gateway.verify_calls == 0


def test_unconfigured_webhook_no_fake_verification(api):
    api.setup.service.gateway = UnconfiguredOnlinePaymentGateway()
    response = api.client.post(
        "/api/v1/payments/webhooks/future", json={"status": "PAID"}
    )
    assert response.status_code == 503 and not api.setup.db.events


def test_no_test_success_or_arbitrary_patch_endpoint(api):
    assert (
        api.client.post(
            "/api/v1/payments/test/success", json={"status": "PAID"}
        ).status_code
        == 404
    )
    assert api.client.patch(api.base, json={"status": "PAID"}).status_code == 405


def test_payment_openapi_has_four_operations_and_no_webhook_jwt(api):
    schema = api.client.get("/openapi.json").json()
    paths = {
        p: v
        for p, v in schema["paths"].items()
        if p.startswith(("/api/v1/payments", "/api/v1/admin/payments"))
        and "/refund" not in p
    }
    assert len(paths) == 4 and sum(len(v) for v in paths.values()) == 4
    assert (
        paths["/api/v1/payments/webhooks/{provider_code}"]["post"].get("security")
        is None
    )
    for path, items in paths.items():
        for operation in items.values():
            assert all(
                str(code) in operation["responses"]
                for code in (401, 403, 404, 409, 422, 503)
            )
            if "/webhooks/" not in path:
                assert operation["security"] == [{"HTTPBearer": []}]
    online = paths["/api/v1/payments/orders/{order_id}/online"]["post"]
    header = next(p for p in online["parameters"] if p["name"] == "Idempotency-Key")
    assert header["required"] and header["in"] == "header"
    assert (
        schema["components"]["schemas"]["EmptyRequest"]["additionalProperties"] is False
    )
