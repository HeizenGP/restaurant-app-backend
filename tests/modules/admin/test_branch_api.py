from uuid import UUID, uuid4

import pytest

from app.shared.application.administration import AdministrationConflict
from tests.modules.admin.test_domain import closed_hours


@pytest.mark.parametrize("who", ["guest", "customer", "kitchen", "foreign"])
def test_branch_management_and_configuration_require_current_branch_permission(
    admin_api, who
):
    root = "/api/v1/admin/branches"
    headers = admin_api.headers(who)
    assert admin_api.client.get(root, headers=headers).status_code == 403
    assert (
        admin_api.client.get(
            root + "/" + str(admin_api.setup.branch) + "/configuration", headers=headers
        ).status_code
        == 403
    )


def test_branch_lifecycle_code_hours_defaults_timezone_and_safe_soft_delete(admin_api):
    root = "/api/v1/admin/branches"
    headers = admin_api.headers("admin")
    body = {
        "code": "new-test",
        "name": "New Branch",
        "address_line": "Test street",
        "district": "Test",
        "hours": closed_hours(),
    }
    created = admin_api.client.post(root, headers=headers, json=body)
    assert created.status_code == 201
    b = created.json()
    assert b["code"] == "NEW-TEST" and len(b["hours"]) == 7
    path = root + "/" + b["id"]
    assert admin_api.client.get(path, headers=headers).status_code == 200
    changed = admin_api.client.patch(
        path, headers=headers, json={"timezone": "Asia/Tokyo", "name": "Changed"}
    )
    assert changed.status_code == 200 and changed.json()["timezone"] == "Asia/Tokyo"
    admin_api.branch_orders.synchronize_timezone.assert_awaited_once()
    invalid = admin_api.client.patch(
        path, headers=headers, json={"timezone": "invalid/not-zone"}
    )
    assert (
        invalid.status_code == 422
        and invalid.json()["error"]["code"] == "BRANCH_TIMEZONE_INVALID"
    )
    overnight = closed_hours()
    overnight[0] = {
        "day_of_week": 0,
        "open_time": "22:00",
        "close_time": "02:00",
        "is_closed": False,
    }
    replaced = admin_api.client.put(
        path + "/hours", headers=headers, json={"hours": overnight}
    )
    assert replaced.status_code == 200 and replaced.json()[0]["close_time"].startswith(
        "02:00"
    )
    assert admin_api.client.get(path + "/hours", headers=headers).status_code == 200
    assert admin_api.client.delete(path, headers=headers).status_code == 204
    assert not admin_api.managed_branches[UUID(b["id"])]["is_active"]
    assert len(admin_api.client.get(root, headers=headers).json()) == 1
    assert (
        admin_api.client.patch(
            path, headers=headers, json={"is_active": True}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "key", ["code", "id", "is_active", "deleted_at", "created_at", "hours"]
)
def test_branch_patch_forbids_identity_and_lifecycle_fields(admin_api, key):
    path = "/api/v1/admin/branches/" + str(admin_api.setup.branch)
    assert (
        admin_api.client.patch(
            path, headers=admin_api.headers("admin"), json={key: "injected"}
        ).status_code
        == 422
    )


def test_branch_foreign_id_cannot_be_read_or_modified(admin_api):
    path = "/api/v1/admin/branches/" + str(uuid4())
    assert (
        admin_api.client.get(path, headers=admin_api.headers("admin")).status_code
        == 403
    )
    assert (
        admin_api.client.patch(
            path, headers=admin_api.headers("admin"), json={"name": "Changed"}
        ).status_code
        == 403
    )
    assert (
        admin_api.client.delete(path, headers=admin_api.headers("admin")).status_code
        == 403
    )


def test_configuration_is_typed_read_only_and_reuses_official_owners(admin_api):
    path = "/api/v1/admin/branches/" + str(admin_api.setup.branch) + "/configuration"
    response = admin_api.client.get(path, headers=admin_api.headers("admin"))
    assert response.status_code == 200
    body = response.json()
    assert len(body["hours"]) == 7 and body["table_count"] == 0
    assert body["order_settings"]["delivery_minimum_order"] == "0.00"
    assert not {"password_hash", "jwt", "push_token"} & body.keys()
    assert (
        admin_api.client.patch(
            path, headers=admin_api.headers("admin"), json={"anything": "injected"}
        ).status_code
        == 405
    )


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?search=x",
        "?search=Test&limit=0",
        "?search=Test&limit=101",
        "?search=Test&user_id=injected",
    ],
)
def test_candidates_search_required_bounded_and_forbids_injections(admin_api, query):
    path = "/api/v1/admin/branches/" + str(admin_api.setup.branch) + "/staff/candidates"
    assert (
        admin_api.client.get(
            path + query, headers=admin_api.headers("admin")
        ).status_code
        == 422
    )


def test_candidates_safe_projection_with_real_bearer(admin_api):
    path = (
        "/api/v1/admin/branches/"
        + str(admin_api.setup.branch)
        + "/staff/candidates?search=Test&limit=10"
    )
    response = admin_api.client.get(path, headers=admin_api.headers("admin"))
    assert response.status_code == 200 and response.json()[0]["already_assigned"]
    assert "password_hash" not in response.text and "TEST private" not in response.text
    assert (
        admin_api.client.get(path, headers=admin_api.headers("kitchen")).status_code
        == 403
    )


@pytest.mark.parametrize(
    "code", ["REGISTERED_CUSTOMER_CANNOT_BE_DELETED", "CUSTOMER_HAS_HISTORY"]
)
def test_customer_delete_conflicts_safe_409(admin_api, code):
    admin_api.customer_repo.delete_customer.side_effect = AdministrationConflict(
        code, "Customer cannot be deleted"
    )
    path = admin_api.customers_path + "/" + str(admin_api.customer_row.id)
    response = admin_api.client.delete(path, headers=admin_api.headers("admin"))
    assert response.status_code == 409 and response.json()["error"]["code"] == code
    admin_api.customer_repo.rollback.assert_awaited_once()


def test_customer_patch_and_unused_guest_delete_statuses(admin_api):
    path = admin_api.customers_path + "/" + str(admin_api.customer_row.id)
    updated = admin_api.client.patch(
        path, headers=admin_api.headers("admin"), json={"full_name": "Changed"}
    )
    assert updated.status_code == 200
    response = admin_api.client.delete(path, headers=admin_api.headers("admin"))
    assert response.status_code == 204 and response.content == b""
