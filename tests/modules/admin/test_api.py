from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.shared.application.exceptions import DependencyUnavailableError


@pytest.mark.parametrize("who", ["customer", "guest", "foreign", "kitchen"])
def test_dashboard_real_jwt_non_admin_rejected(admin_api, who):
    response = admin_api.client.get(
        "/api/v1/admin/dashboard", headers=admin_api.headers(who)
    )
    assert response.status_code == 403


def test_dashboard_bearer_required_and_revoked_assignment(admin_api):
    assert admin_api.client.get("/api/v1/admin/dashboard").status_code == 401
    admin_api.grants = False
    assert (
        admin_api.client.get(
            "/api/v1/admin/dashboard", headers=admin_api.headers("admin")
        ).status_code
        == 403
    )


def test_dashboard_zero_is_safe_decimal_and_branch_scoped(admin_api):
    response = admin_api.client.get(
        "/api/v1/admin/dashboard", headers=admin_api.headers("admin")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["currency_code"] == "PEN"
    assert body["summary"]["gross_sales"] == "0.00"
    assert body["summary"]["orders_count"] == 0
    assert len(body["sales_by_mode"]) == 3
    assert len(body["sales_by_branch"]) == 1
    assert body["sales_by_branch"][0]["branch_id"] == str(admin_api.setup.branch)
    assert body["top_products"] == []


@pytest.mark.parametrize(
    "query",
    [
        "?timezone=UTC",
        "?customer_id=bad",
        "?limit=1000",
        "?from_date=bad",
        "?from_date=2026-10-08&to_date=2026-10-07",
        "?from_date=2026-01-01&to_date=2026-02-01",
    ],
)
def test_dashboard_rejects_unknown_and_invalid_period(admin_api, query):
    response = admin_api.client.get(
        "/api/v1/admin/dashboard" + query, headers=admin_api.headers("admin")
    )
    assert response.status_code == 422


def test_dashboard_exact_foreign_branch_is_403(admin_api):
    response = admin_api.client.get(
        "/api/v1/admin/dashboard?branch_id=" + str(uuid4()),
        headers=admin_api.headers("admin"),
    )
    assert response.status_code == 403


@pytest.mark.parametrize("who", ["customer", "guest", "foreign", "kitchen"])
def test_customers_reject_wrong_roles_with_real_jwt(admin_api, who):
    assert (
        admin_api.client.get(
            admin_api.customers_path, headers=admin_api.headers(who)
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=101",
        "?offset=-1",
        "?offset=10001",
        "?search=x",
        "?search=" + "x" * 81,
        "?user_id=bad",
        "?phone_verified_at=bad",
    ],
)
def test_customers_bounded_search_forbids_server_fields(admin_api, query):
    assert (
        admin_api.client.get(
            admin_api.customers_path + query, headers=admin_api.headers("admin")
        ).status_code
        == 422
    )


def test_customer_list_safe_projection_and_prefix_params(admin_api):
    response = admin_api.client.get(
        admin_api.customers_path + "?search=Cust&limit=10&offset=2",
        headers=admin_api.headers("admin"),
    )
    assert response.status_code == 200
    assert (
        not {"user_id", "password_hash", "addresses", "created_by_branch_id"}
        & response.json()[0].keys()
    )
    args = admin_api.customer_repo.list_customers.await_args.args
    assert args[1:] == ("Cust", 10, 2)


@pytest.mark.parametrize(
    "key",
    [
        "user_id",
        "password",
        "is_guest",
        "phone_verified_at",
        "created_at",
        "created_by_branch_id",
    ],
)
def test_admin_customer_create_rejects_owned_identity_fields(admin_api, key):
    response = admin_api.client.post(
        admin_api.customers_path,
        headers=admin_api.headers("admin"),
        json={"full_name": "Test", "phone": "+51912345678", key: "injected"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "key",
    ["phone", "user_id", "password", "is_guest", "phone_verified_at", "created_at"],
)
def test_admin_customer_patch_rejects_server_fields(admin_api, key):
    response = admin_api.client.patch(
        admin_api.customers_path + "/" + str(admin_api.customer_row.id),
        headers=admin_api.headers("admin"),
        json={key: "injected"},
    )
    assert response.status_code == 422


def test_admin_creation_has_no_user_or_tokens_and_normal_otp_promotes_same_customer(
    admin_api,
):
    phone = "+51912345678"
    before_users = len(admin_api.auth.users)
    created = admin_api.client.post(
        admin_api.customers_path,
        headers=admin_api.headers("admin"),
        json={"full_name": "Admin contact", "phone": phone},
    )
    assert created.status_code == 201
    id_ = UUID(created.json()["id"])
    assert created.json()["is_guest"] and created.json()["phone_verified_at"] is None
    assert (
        not {"access_token", "refresh_token", "password", "user_id"}
        & created.json().keys()
    )
    assert len(admin_api.auth.users) == before_users
    request = admin_api.client.post(
        "/api/v1/auth/otp/request", json={"phone": phone, "purpose": "REGISTER"}
    )
    assert request.status_code == 202
    verified = admin_api.client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": phone,
            "purpose": "REGISTER",
            "code": request.json()["debug_code"],
        },
    )
    assert verified.status_code == 200
    registered = admin_api.client.post(
        "/api/v1/auth/register",
        json={
            "verification_token": verified.json()["verification_token"],
            "first_name": "Verified",
            "last_name": "Customer",
            "password": "phase10-test-only-safe-password",
        },
    )
    assert registered.status_code == 201
    identity = admin_api.auth.customers[id_]
    assert identity.user_id is not None and identity.phone_verified_at is not None
    assert identity.full_name == "Verified Customer"
    assert len([c for c in admin_api.auth.customers.values() if c.phone == phone]) == 1


def test_customer_idor_403_before_repository_and_404_inside_scope(admin_api):
    foreign = admin_api.customers_path.replace(
        str(admin_api.setup.branch), str(uuid4())
    )
    assert (
        admin_api.client.get(
            foreign + "/" + str(uuid4()), headers=admin_api.headers("admin")
        ).status_code
        == 403
    )
    admin_api.customer_repo.get_customer.assert_not_called()
    admin_api.customer_repo.get_customer.return_value = None
    response = admin_api.client.get(
        admin_api.customers_path + "/" + str(uuid4()),
        headers=admin_api.headers("admin"),
    )
    assert (
        response.status_code == 404
        and response.json()["error"]["code"] == "ADMIN_CUSTOMER_NOT_FOUND"
    )


def test_database_unavailability_safe_503(admin_api):
    admin_api.customer_repo.list_customers.side_effect = DependencyUnavailableError(
        "Database is unavailable"
    )
    response = admin_api.client.get(
        admin_api.customers_path, headers=admin_api.headers("admin")
    )
    assert response.status_code == 503
    assert (
        "sql" not in response.text.lower() and "password" not in response.text.lower()
    )


def test_account_blocking_invalidates_same_signed_jwt(admin_api):
    user = admin_api.auth.users[admin_api.setup.admin.user_id]
    admin_api.auth.users[user.id] = replace(user, account_status="BLOCKED")
    response = admin_api.client.get(
        "/api/v1/admin/dashboard", headers=admin_api.headers("admin")
    )
    assert response.status_code == 403


def test_staff_new_and_legacy_routes_share_last_admin_guard(admin_api):
    branch = admin_api.setup.branch
    path = "/api/v1/admin/branches/" + str(branch) + "/staff"
    body = {
        "user_id": str(admin_api.setup.admin.user_id),
        "role_code": "ADMIN",
        "employee_code": "OWNER",
    }
    response = admin_api.client.post(
        path, json=body, headers=admin_api.headers("admin")
    )
    assert response.status_code == 201
    assignment = response.json()["id"]
    for route in (path, "/api/v1/branches/" + str(branch) + "/staff"):
        blocked = admin_api.client.patch(
            route + "/" + assignment,
            json={"role_code": "KITCHEN"},
            headers=admin_api.headers("admin"),
        )
        assert (
            blocked.status_code == 409
            and blocked.json()["error"]["code"] == "LAST_BRANCH_ADMIN"
        )
    assert (
        admin_api.client.delete(
            path + "/" + assignment, headers=admin_api.headers("admin")
        ).status_code
        == 409
    )
