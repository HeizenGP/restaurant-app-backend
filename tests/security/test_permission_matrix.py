from dataclasses import replace
from uuid import uuid4

import jwt
import pytest

from scripts.contracts import contract_app


def admin_targets(s):
    branch = str(s.api.setup.branch)
    return [
        "/api/v1/admin/reviews/branches/" + branch,
        "/api/v1/admin/receipts/branches/" + branch,
        "/api/v1/admin/promotions/branches/" + branch + "/roulette/campaigns",
        s.api.admin + "/events",
    ]


@pytest.mark.parametrize(
    "who,expected",
    [
        (None, 401),
        ("guest", 403),
        ("customer", 403),
        ("kitchen", 403),
        ("foreign", 403),
        ("admin", 200),
    ],
)
def test_registered_role_permission_matrix(extras_api, who, expected):
    s = extras_api
    for target in admin_targets(s):
        response = s.client.get(target, headers=s.headers(who) if who else {})
        assert response.status_code == expected, (who, target, response.text)


@pytest.mark.parametrize("module", ["reviews", "receipts", "promotions"])
def test_permission_revocation_applies_to_next_request_same_token(extras_api, module):
    s = extras_api
    target = admin_targets(s)[["reviews", "receipts", "promotions"].index(module)]
    assert s.client.get(target, headers=s.headers("admin")).status_code == 200
    getattr(s, module).authorization.enabled = False
    assert s.client.get(target, headers=s.headers("admin")).status_code == 403


def test_inactive_user_rejected_before_admin_operation(extras_api):
    s = extras_api
    user = s.api.setup.admin.user_id
    s.api.auth.users[user] = replace(s.api.auth.users[user], account_status="BLOCKED")
    for target in admin_targets(s):
        response = s.client.get(target, headers=s.headers("admin"))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ACCOUNT_BLOCKED"


def test_signed_role_and_permission_claims_do_not_grant_admin(extras_api):
    s = extras_api
    payload = jwt.decode(s.api.tokens["customer"], options={"verify_signature": False})
    payload.update(role="ADMIN", permissions=["*"], branch_id=str(s.api.setup.branch))
    token = jwt.encode(
        payload,
        "notifications-tests-only-signing-key-at-least-32-characters",
        algorithm="HS256",
    )
    for target in admin_targets(s):
        assert (
            s.client.get(
                target, headers={"Authorization": "Bearer " + token}
            ).status_code
            == 403
        )


def test_every_protected_operation_rejects_missing_credentials(client):
    schema = contract_app().openapi()
    count = 0
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if not operation.get("security"):
                continue
            target = path
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "path":
                    target = target.replace("{" + parameter["name"] + "}", str(uuid4()))
            response = client.request(
                method, target, json={} if method in {"post", "patch", "put"} else None
            )
            assert response.status_code == 401, (method, path, response.status_code)
            count += 1
    assert count > 100
