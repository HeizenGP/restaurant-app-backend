from dataclasses import replace
from uuid import uuid4

import pytest


def path(s):
    return "/api/v1/orders/" + str(s.reviews.orders.order.id) + "/review"


@pytest.mark.parametrize("who", ["customer", "guest"])
def test_completed_order_review_jwt_owner_duplicate_and_admin_rating_filter(
    extras_api, who
):
    s = extras_api
    s.reviews.orders.order = replace(
        s.reviews.orders.order, customer_id=getattr(s.api.setup, who).customer_id
    )
    result = s.client.post(
        path(s), json={"rating": 5, "comment": " Good "}, headers=s.headers(who)
    )
    assert result.status_code == 201 and result.json()["comment"] == "Good"
    assert "customer_id" not in result.json()
    assert s.client.get(path(s), headers=s.headers(who)).json() == result.json()
    assert s.client.get(path(s), headers=s.headers("foreign")).status_code == 404
    again = s.client.post(path(s), json={"rating": 1}, headers=s.headers(who))
    assert (
        again.status_code == 409
        and again.json()["error"]["code"] == "ORDER_ALREADY_REVIEWED"
    )
    admin = "/api/v1/admin/reviews/branches/" + str(s.reviews.branch)
    rows = s.client.get(admin + "?rating=5", headers=s.headers("admin"))
    assert rows.status_code == 200 and len(rows.json()) == 1
    assert not {"customer_id", "phone", "email"} & rows.json()[0].keys()
    assert s.client.get(admin + "?rating=4", headers=s.headers("admin")).json() == []


@pytest.mark.parametrize(
    "body",
    [
        {"rating": 0},
        {"rating": 6},
        {"rating": True},
        {"rating": 5.0},
        {"rating": "5"},
        {"rating": 5, "comment": "<script>private</script>"},
        {"rating": 5, "customer_id": "private"},
        {"rating": 5, "branch_id": "private"},
        {"rating": 5, "order_id": "private"},
        {"rating": 5, "comment": "private" * 150},
    ],
)
def test_invalid_body_extra_identity_and_unsafe_comments_422(extras_api, body):
    s = extras_api
    response = s.client.post(path(s), json=body, headers=s.headers())
    assert (
        response.status_code == 422
        and "private" not in response.text
        and not s.reviews.repo.rows
    )


@pytest.mark.parametrize("who", ["customer", "guest", "kitchen"])
def test_admin_scope_real_principal_does_not_grant_via_jwt_identity(extras_api, who):
    s = extras_api
    response = s.client.get(
        "/api/v1/admin/reviews/branches/" + str(s.reviews.branch),
        headers=s.headers(who),
    )
    assert response.status_code == 403


def test_no_auth_order_pending_scope_revocation_and_immutable_endpoints(extras_api):
    s = extras_api
    assert s.client.post(path(s), json={"rating": 5}).status_code == 401
    s.reviews.orders.order = replace(s.reviews.orders.order, status="WAITING")
    response = s.client.post(path(s), json={"rating": 5}, headers=s.headers())
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "ORDER_NOT_REVIEWABLE"
    )
    assert (
        s.client.patch(path(s), json={"rating": 5}, headers=s.headers()).status_code
        == 405
    )
    assert s.client.delete(path(s), headers=s.headers()).status_code == 405
    s.reviews.authorization.enabled = False
    base = "/api/v1/admin/reviews/branches/"
    assert (
        s.client.get(
            base + str(s.reviews.branch), headers=s.headers("admin")
        ).status_code
        == 403
    )
    assert (
        s.client.get(base + str(uuid4()), headers=s.headers("admin")).status_code == 403
    )


@pytest.mark.parametrize(
    "query",
    [
        "customer_id=private",
        "timezone=private",
        "rating=0",
        "limit=101",
        "from_date=2026-10-08&to_date=2026-10-07",
    ],
)
def test_admin_filters_validation(extras_api, query):
    s = extras_api
    response = s.client.get(
        "/api/v1/admin/reviews/branches/" + str(s.reviews.branch) + "?" + query,
        headers=s.headers("admin"),
    )
    assert response.status_code == 422 and "private" not in response.text
