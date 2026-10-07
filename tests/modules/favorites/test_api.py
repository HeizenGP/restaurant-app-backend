from dataclasses import replace

import pytest


def path(s):
    return "/api/v1/favorites/" + str(s.favorites.catalog.product.id)


def test_put_delete_get_public_catalog_projection_owner_and_idempotence(extras_api):
    s = extras_api
    first = s.client.put(path(s), headers=s.headers())
    assert first.status_code == 200
    assert s.client.put(path(s), headers=s.headers()).json() == first.json()
    query = "?branch_id=" + str(s.favorites.branch)
    rows = s.client.get("/api/v1/favorites" + query, headers=s.headers()).json()
    assert len(rows) == 1 and rows[0]["product"]["name"] == "Original product"
    assert "user_id" not in rows[0] and "customer_id" not in rows[0]
    assert (
        s.client.get("/api/v1/favorites" + query, headers=s.headers("foreign")).json()
        == []
    )
    assert s.client.delete(path(s), headers=s.headers("foreign")).status_code == 204
    assert len(s.favorites.repo.rows) == 1
    assert s.client.delete(path(s), headers=s.headers()).status_code == 204
    assert s.client.delete(path(s), headers=s.headers()).status_code == 204
    assert not s.favorites.repo.rows


@pytest.mark.parametrize(
    "method,suffix", [("put", "product"), ("delete", "product"), ("get", "list")]
)
def test_guest_registered_required_and_auth_required(extras_api, method, suffix):
    s = extras_api
    target = (
        path(s)
        if suffix == "product"
        else "/api/v1/favorites?branch_id=" + str(s.favorites.branch)
    )
    assert s.client.request(method, target).status_code == 401
    response = s.client.request(method, target, headers=s.headers("guest"))
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "REGISTERED_ACCOUNT_REQUIRED"
    )


@pytest.mark.parametrize(
    "query", ["user_id=secret", "customer_id=secret", "limit=101", "offset=-1"]
)
def test_extra_query_forbidden_and_private_input_not_echoed(extras_api, query):
    s = extras_api
    response = s.client.get(
        "/api/v1/favorites?branch_id=" + str(s.favorites.branch) + "&" + query,
        headers=s.headers(),
    )
    assert response.status_code == 422 and "secret" not in response.text


def test_blocked_user_rejected_even_with_existing_signed_jwt(extras_api):
    s = extras_api
    user = s.api.auth.users[s.api.setup.customer.user_id]
    s.api.auth.users[user.id] = replace(user, account_status="BLOCKED")
    assert s.client.put(path(s), headers=s.headers()).status_code == 403
    assert not s.favorites.repo.rows
