from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.infrastructure.refund_gateway import (
    UnconfiguredOnlineRefundGateway,
)
from tests.modules.payments.fakes import signed_event


def request(api):
    r = api.client.post(
        api.customer, json={"reason": "Plans changed"}, headers=api.headers("customer")
    )
    assert r.status_code == 201, r.text
    return r.json()


def cancel(api):
    r = api.client.post(
        api.cancel, json={"reason_code": "OUT_OF_STOCK"}, headers=api.headers()
    )
    assert r.status_code == 200, r.text
    return r.json()


def targets(api):
    rid = str(uuid4())
    return [
        ("post", api.customer, {"reason": "Plans changed"}, "customer"),
        ("get", api.customer, None, "customer"),
        ("get", api.base + "/requests", None, "admin"),
        ("post", api.base + "/requests/" + rid + "/approve", {}, "admin"),
        ("post", api.base + "/requests/" + rid + "/reject", {}, "admin"),
        ("post", api.cancel, {"reason_code": "OUT_OF_STOCK"}, "admin"),
        ("get", api.base + "/orders/" + str(api.setup.order.id), None, "admin"),
        ("get", api.refund_customer, None, "customer"),
        ("get", api.refunds, None, "admin"),
        ("get", api.refunds + "/" + rid, None, "admin"),
        ("post", api.refunds + "/" + rid + "/cash/confirm", {}, "admin"),
        ("post", api.refunds + "/" + rid + "/online/process", {}, "admin"),
    ]


@pytest.mark.parametrize("index", range(12))
def test_all_business_routes_require_real_jwt(api, index):
    method, path, body, _ = targets(api)[index]
    kwargs = {"headers": {"Idempotency-Key": "refund-key"}}
    if body is not None:
        kwargs["json"] = body
    result = getattr(api.client, method)(path, **kwargs)
    assert result.status_code == 401, result.text
    assert not api.setup.db.cancellations and not api.setup.db.refunds


@pytest.mark.parametrize("index", range(2, 12))
@pytest.mark.parametrize("who", ["kitchen", "customer", "guest"])
def test_no_privileged_access_for_non_admin(api, index, who):
    method, path, body, _ = targets(api)[index]
    if index == 7:  # Customer read is owned; foreign principals are tested separately.
        return
    kwargs = {"headers": api.headers(who, key="refund-key")}
    if body is not None:
        kwargs["json"] = body
    result = getattr(api.client, method)(path, **kwargs)
    assert result.status_code == 403, result.text
    assert not api.setup.db.cancellations and not api.setup.db.refunds


def test_create_retry_conflict_and_owner_safe_projection(api):
    r = request(api)
    assert r["status"] == "PENDING"
    for private in (
        "customer_id",
        "branch_id",
        "evaluated_by_user_id",
        "evaluation_note",
    ):
        assert private not in r
    same = api.client.post(
        api.customer,
        json={"reason": "  Plans changed  "},
        headers=api.headers("customer"),
    )
    assert same.status_code == 200 and same.json()["id"] == r["id"]
    other = api.client.post(
        api.customer, json={"reason": "Different"}, headers=api.headers("customer")
    )
    assert other.status_code == 409
    assert (
        len(api.client.get(api.customer, headers=api.headers("customer")).json()) == 1
    )
    assert not api.setup.db.cancellations and not api.setup.db.refunds


@pytest.mark.parametrize("method", ["get", "post"])
def test_customer_idor_returns_404(api, method):
    kwargs = {"headers": api.headers("foreign")}
    if method == "post":
        kwargs["json"] = {"reason": "Plans"}
    assert getattr(api.client, method)(api.customer, **kwargs).status_code == 404


def test_guest_customer_request_uses_real_identity(api):
    api.setup.db.orders[api.setup.order.id] = replace(
        api.setup.order, customer_id=api.setup.guest.customer_id
    )
    assert (
        api.client.post(
            api.customer, json={"reason": "Plans"}, headers=api.headers("guest")
        ).status_code
        == 201
    )


@pytest.mark.parametrize(
    "reason", ["", " ", "<b>HTML</b>", "x\nnext", "x\x00", "x\u200b", "x" * 1001]
)
def test_reason_validation_never_mutates(api, reason):
    assert (
        api.client.post(
            api.customer, json={"reason": reason}, headers=api.headers("customer")
        ).status_code
        == 422
    )
    assert not api.setup.db.requests


@pytest.mark.parametrize(
    "field",
    [
        "customer_id",
        "branch_id",
        "status",
        "requested_at",
        "evaluated_at",
        "refund_amount",
        "order_id",
    ],
)
def test_customer_cannot_inject_owned_fields(api, field):
    assert (
        api.client.post(
            api.customer,
            json={"reason": "Plans", field: "injected"},
            headers=api.headers("customer"),
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "body",
    [
        {"reason_code": "OTHER"},
        {"reason_code": "CUSTOMER_REQUEST"},
        {"reason_code": "OUT_OF_STOCK", "source": "CUSTOMER_REQUEST"},
        {"reason_code": "OTHER", "reason": "<b>HTML</b>"},
        {"reason_code": "OUT_OF_STOCK", "status": "CANCELLED"},
        {"reason_code": "OUT_OF_STOCK", "amount": "1.00"},
    ],
)
def test_admin_body_is_strict(api, body):
    assert (
        api.client.post(api.cancel, json=body, headers=api.headers()).status_code == 422
    )
    assert not api.setup.db.cancellations


def test_approval_rejection_and_admin_queue(api):
    r = request(api)
    rows = api.client.get(api.base + "/requests", headers=api.headers())
    assert rows.status_code == 200 and rows.json()[0]["id"] == r["id"]
    path = api.base + "/requests/" + r["id"] + "/approve"
    result = api.client.post(
        path, json={"evaluation_note": "Reviewed"}, headers=api.headers()
    )
    assert result.status_code == 200, result.text
    assert result.json()["refund"]["status"] == "PENDING"
    assert (
        api.client.post(
            path, json={"evaluation_note": "Reviewed"}, headers=api.headers()
        ).status_code
        == 200
    )
    assert (
        api.client.post(
            path, json={"evaluation_note": "Different"}, headers=api.headers()
        ).status_code
        == 409
    )
    assert api.client.get(api.base + "/requests", headers=api.headers()).json() == []
    assert (
        len(
            api.client.get(
                api.base + "/requests?status=APPROVED", headers=api.headers()
            ).json()
        )
        == 1
    )
    assert (
        api.client.post(
            api.base + "/requests/" + r["id"] + "/reject",
            json={},
            headers=api.headers(),
        ).status_code
        == 409
    )


def test_reject_keeps_history_then_new_request(api):
    r = request(api)
    result = api.client.post(
        api.base + "/requests/" + r["id"] + "/reject", json={}, headers=api.headers()
    )
    assert result.status_code == 200 and result.json()["status"] == "REJECTED"
    assert not api.setup.db.cancellations and not api.setup.db.refunds
    assert request(api)["id"] != r["id"]


def test_direct_cancel_detail_and_refund_privacy(api):
    out = cancel(api)
    refund = out["refund"]
    assert (
        api.client.post(
            api.cancel, json={"reason_code": "OUT_OF_STOCK"}, headers=api.headers()
        ).status_code
        == 200
    )
    path = api.base + "/orders/" + str(api.setup.order.id)
    assert api.client.get(path, headers=api.headers()).json() == out
    safe = api.client.get(api.refund_customer, headers=api.headers("customer"))
    assert safe.status_code == 200
    assert set(safe.json()) == {
        "id",
        "order_id",
        "amount",
        "currency_code",
        "method_type",
        "status",
        "requested_at",
        "refunded_at",
    }
    assert (
        api.client.get(api.refund_customer, headers=api.headers("foreign")).status_code
        == 404
    )
    detail = api.client.get(api.refunds + "/" + refund["id"], headers=api.headers())
    assert detail.status_code == 200 and len(detail.json()["history"]) == 1
    assert (
        api.client.get(
            api.refunds + "?status=PENDING&method_type=ONLINE", headers=api.headers()
        ).status_code
        == 200
    )


def test_missing_coherent_payment_is_503_and_rollback(api):
    api.setup.db.payments.clear()
    result = api.client.post(
        api.cancel, json={"reason_code": "OUT_OF_STOCK"}, headers=api.headers()
    )
    assert result.status_code == 503
    assert not api.setup.db.cancellations and not api.setup.db.refunds
    assert api.setup.db.orders[api.setup.order.id] == api.setup.order


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "unknown=yes", "status=PAID"]
)
def test_queue_query_validated(api, query):
    assert (
        api.client.get(
            api.base + "/requests?" + query, headers=api.headers()
        ).status_code
        == 422
    )
    assert (
        api.client.get(api.refunds + "?" + query, headers=api.headers()).status_code
        == 422
    )


@pytest.mark.parametrize(
    "field", ["amount", "currency_code", "provider_reference", "status", "refund_id"]
)
def test_financial_post_cannot_accept_server_fields(api, field):
    r = cancel(api)["refund"]
    path = api.refunds + "/" + r["id"] + "/online/process"
    assert (
        api.client.post(
            path, json={field: "injected"}, headers=api.headers(key="refund-key")
        ).status_code
        == 422
    )
    assert not api.setup.db.refund_attempts


@pytest.mark.parametrize("key", [None, "", "contains spaces", "x" * 201])
def test_refund_key_required_and_valid(api, key):
    r = cancel(api)["refund"]
    path = api.refunds + "/" + r["id"] + "/online/process"
    assert (
        api.client.post(path, json={}, headers=api.headers(key=key)).status_code == 422
    )
    assert not api.setup.db.refund_attempts


def test_real_production_adapter_reports_503_without_writes(api):
    r = cancel(api)["refund"]
    api.setup.refund_service.gateway = UnconfiguredOnlineRefundGateway()
    path = api.refunds + "/" + r["id"] + "/online/process"
    assert (
        api.client.post(
            path, json={}, headers=api.headers(key="refund-key")
        ).status_code
        == 503
    )
    assert not api.setup.db.refund_attempts


def test_online_process_verified_webhook_and_safe_detail(api):
    r = cancel(api)["refund"]
    path = api.refunds + "/" + r["id"] + "/online/process"
    result = api.client.post(path, json={}, headers=api.headers(key="refund-key"))
    assert result.status_code == 200, result.text
    assert result.json()["refund"]["status"] == "PROCESSING"
    a = next(iter(api.setup.db.refund_attempts.values()))
    body, headers = signed_event(a)
    webhook = "/api/v1/payments/refund-webhooks/test_gateway"
    assert api.client.post(webhook, content=body, headers=headers).status_code == 200
    assert api.client.post(webhook, content=body, headers=headers).status_code == 200
    assert (
        api.client.get(api.refund_customer, headers=api.headers("customer")).json()[
            "status"
        ]
        == "REFUNDED"
    )
    detail = api.client.get(api.refunds + "/" + r["id"], headers=api.headers()).json()
    assert len(detail["attempts"]) == 1 and len(detail["history"]) == 3
    public = repr(detail)
    for secret in (
        "provider_reference",
        "idempotency_key",
        "provider_event_id",
        "payload_hash",
    ):
        assert secret not in public


def test_cash_confirm_actual_return_and_retry(api):
    s = api.setup
    s.db.orders[s.order.id] = replace(
        s.order, payment_method_type=PaymentMethodType.CASH
    )
    for pid, p in list(s.db.payments.items()):
        s.db.payments[pid] = replace(p, method_type=PaymentMethodType.CASH)
    r = cancel(api)["refund"]
    path = api.refunds + "/" + r["id"] + "/cash/confirm"
    response = api.client.post(path, headers=api.headers())
    assert response.status_code == 200 and response.json()["status"] == "REFUNDED"
    assert (
        api.client.post(path, json={}, headers=api.headers()).json() == response.json()
    )


def test_webhook_is_not_jwt_but_must_be_verified(api):
    path = "/api/v1/payments/refund-webhooks/test_gateway"
    assert api.client.post(path, content=b"{}").status_code == 401
    assert not api.setup.db.refund_events
    assert api.client.post(path, content=b"x" * 65537).status_code == 422


def test_current_permission_revocation_is_effective(api):
    api.setup.authz.grants.clear()
    assert (
        api.client.post(
            api.cancel, json={"reason_code": "OUT_OF_STOCK"}, headers=api.headers()
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "changes", [{"account_status": "BLOCKED"}, {"deleted_at": None}]
)
def test_blocked_or_deleted_user_cannot_use_signed_old_token(api, changes):
    from app.shared.domain.time import utc_now

    if "deleted_at" in changes:
        changes = {"deleted_at": utc_now()}
    uid = api.setup.admin.user_id
    api.auth.users[uid] = replace(api.auth.users[uid], **changes)
    assert api.client.post(
        api.cancel, json={"reason_code": "OUT_OF_STOCK"}, headers=api.headers()
    ).status_code in {401, 403}


def test_cross_branch_lookup_returns_404_after_permission(api):
    other = uuid4()
    api.setup.authz.grants.add((api.setup.admin.user_id, other, "CANCELLATION_MANAGE"))
    path = api.cancel.replace(str(api.setup.branch), str(other))
    assert (
        api.client.post(
            path, json={"reason_code": "OUT_OF_STOCK"}, headers=api.headers()
        ).status_code
        == 404
    )


def test_openapi_documents_thirteen_operations(api):
    paths = api.client.get("/openapi.json").json()["paths"]
    subset = {
        p: v
        for p, v in paths.items()
        if "cancellation" in p or "/refund" in p or "/admin/refunds" in p
    }
    assert len(subset) == 12
    assert (
        sum(
            sum(method in {"get", "post", "put", "patch", "delete"} for method in item)
            for item in subset.values()
        )
        == 13
    )
    assert (
        "201"
        in paths["/api/v1/orders/{order_id}/cancellation-requests"]["post"]["responses"]
    )
