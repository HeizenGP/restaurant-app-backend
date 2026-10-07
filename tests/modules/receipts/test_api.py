from dataclasses import replace
from uuid import uuid4

import pytest


def path(s):
    return "/api/v1/orders/" + str(s.receipts.orders.order.id) + "/receipt"


def admin(s):
    return "/api/v1/admin/receipts/branches/" + str(s.receipts.branch)


def create(s, who="customer"):
    return s.client.post(
        path(s),
        json={"document_type": "BOLETA"},
        headers=s.headers(who, **{"Idempotency-Key": "receipt-1"}),
    )


@pytest.mark.parametrize("who", ["customer", "guest"])
def test_request_owner_decimal_pending_retry_privacy_real_auth_and_unconfigured_503(
    extras_api, who
):
    s = extras_api
    s.receipts.orders.order = replace(
        s.receipts.orders.order, customer_id=getattr(s.api.setup, who).customer_id
    )
    result = create(s, who)
    assert result.status_code == 201
    data = result.json()
    assert (
        data["amount"] == "47.00"
        and data["currency_code"] == "PEN"
        and data["status"] == "PENDING"
    )
    assert (
        "request_key_hash" not in data
        and "request_fingerprint" not in data
        and "customer_id" not in data
    )
    assert data["series"] is data["number"] is data["issued_at"] is None
    assert create(s, who).json() == data
    assert s.client.get(path(s), headers=s.headers(who)).json() == data
    assert s.client.get(path(s), headers=s.headers("foreign")).status_code == 404
    assert s.client.get(admin(s), headers=s.headers("admin")).json() == [data]
    response = s.client.post(
        admin(s) + "/" + data["id"] + "/process",
        headers=s.headers("admin", **{"Idempotency-Key": "attempt-1"}),
    )
    assert (
        response.status_code == 503
        and response.json()["error"]["code"] == "FISCAL_PROVIDER_UNAVAILABLE"
    )
    assert not s.receipts.repo.attempts and len(s.receipts.repo.docs) == 1
    assert s.client.get(path(s), headers=s.headers(who)).json() == data


@pytest.mark.parametrize(
    "extra",
    [
        "amount",
        "currency_code",
        "status",
        "series",
        "number",
        "customer_id",
        "branch_id",
        "provider_code",
        "pdf_url",
        "issued_at",
    ],
)
def test_server_owned_body_fields_rejected_never_echo_private_input(extras_api, extra):
    s = extras_api
    response = s.client.post(
        path(s),
        json={"document_type": "BOLETA", extra: "private-value"},
        headers=s.headers(**{"Idempotency-Key": "one"}),
    )
    assert (
        response.status_code == 422
        and "private-value" not in response.text
        and not s.receipts.repo.docs
    )


@pytest.mark.parametrize(
    "body",
    [
        {"document_type": "FACTURA"},
        {
            "document_type": "FACTURA",
            "recipient_document_type": "RUC",
            "recipient_document_number": "123",
            "recipient_name": "private-name",
            "recipient_address": "private-address",
        },
        {"document_type": "OTHER"},
        {"document_type": "BOLETA", "recipient_name": "private\x00name"},
    ],
)
def test_invalid_factura_data_sanitized_validation(extras_api, body):
    s = extras_api
    response = s.client.post(
        path(s), json=body, headers=s.headers(**{"Idempotency-Key": "one"})
    )
    assert response.status_code == 422 and "private-name" not in response.text
    assert "private-address" not in response.text and not s.receipts.repo.docs


@pytest.mark.parametrize("key", [None, "", "x" * 129, "with space"])
def test_required_valid_idempotency_header(extras_api, key):
    s = extras_api
    headers = s.headers(**({"Idempotency-Key": key} if key is not None else {}))
    response = s.client.post(path(s), json={"document_type": "BOLETA"}, headers=headers)
    assert response.status_code == 422 and not s.receipts.repo.docs


def test_admin_permissions_separate_view_process_foreign_and_blocked_jwt(extras_api):
    s = extras_api
    data = create(s).json()
    process = admin(s) + "/" + data["id"] + "/process"
    key = {"Idempotency-Key": "one"}
    assert s.client.get(path(s)).status_code == 401
    assert s.client.post(process, headers=s.headers(**key)).status_code == 403
    s.receipts.authorization.permissions.remove("RECEIPT_MANAGE")
    assert s.client.get(admin(s), headers=s.headers("admin")).status_code == 200
    assert s.client.post(process, headers=s.headers("admin", **key)).status_code == 403
    s.receipts.authorization.permissions.add("RECEIPT_MANAGE")
    assert (
        s.client.post(
            admin(s) + "/" + str(uuid4()) + "/process",
            headers=s.headers("admin", **key),
        ).status_code
        == 404
    )
    user = s.api.auth.users[s.api.setup.admin.user_id]
    s.api.auth.users[user.id] = replace(user, account_status="BLOCKED")
    assert s.client.get(admin(s), headers=s.headers("admin")).status_code == 403
    assert not s.receipts.repo.attempts
