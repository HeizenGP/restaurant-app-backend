from dataclasses import replace
from uuid import uuid4

import jwt
import pytest

from tests.modules.extras_support import NOW


def base(s):
    return "/api/v1/admin/promotions/branches/" + str(s.promotions.branch)


def campaigns(s):
    return base(s) + "/roulette/campaigns"


def spin(s, who="customer", key="one", extra=None):
    body = {"branch_id": str(s.promotions.branch)} | (extra or {})
    return s.client.post(
        "/api/v1/promotions/roulette/spins",
        json=body,
        headers=s.headers(who, **{"Idempotency-Key": key}),
    )


@pytest.mark.parametrize("who", ["customer", "guest"])
def test_public_roulette_spin_retry_rewards_and_admin_redeem(extras_api, who):
    s = extras_api
    response = s.client.get(
        "/api/v1/promotions/roulette?branch_id=" + str(s.promotions.branch),
        headers=s.headers(who),
    )
    assert response.status_code == 200 and response.json()["can_spin"]
    data = response.json()
    assert (
        data["terms_text"].startswith("Free")
        and data["prizes"][0]["probability_bps"] == 1000
    )
    assert (
        data["no_prize_probability_bps"] == 9000
        and data["prizes"][0]["probability_percent"] == "10"
    )
    first = spin(s, who)
    assert first.status_code == 201 and first.json()["outcome"] == "WIN"
    assert spin(s, who).json() == first.json() and s.promotions.random.calls == 1
    data = first.json()
    assert data["prize"]["product_name"] == "Original product"
    assert (
        not {"random_draw", "configuration_snapshot", "idempotency_key", "customer_id"}
        & data.keys()
    )
    reward = data["reward"]
    assert "customer_id" not in reward and "redeemed_by_user_id" not in reward
    rows = s.client.get("/api/v1/promotions/rewards", headers=s.headers(who)).json()
    assert rows == [reward]
    assert (
        s.client.get("/api/v1/promotions/rewards", headers=s.headers("foreign")).json()
        == []
    )
    target = base(s) + "/rewards/" + reward["id"] + "/redeem"
    assert s.client.post(target, headers=s.headers(who)).status_code == 403
    result = s.client.post(target, headers=s.headers("admin"))
    assert result.status_code == 200 and result.json()["status"] == "REDEEMED"
    assert s.client.post(target, headers=s.headers("admin")).json() == result.json()
    assert len(s.promotions.audit.records) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"outcome": "WIN"},
        {"prize_id": "private"},
        {"customer_id": "private"},
        {"probability_bps": 10000},
        {"reward": {"amount": "0"}},
        {"random_draw": 0},
        {"campaign_id": "private"},
        {"expires_at": "private"},
        {"payment_id": "private"},
        {"tokens": 1},
    ],
)
def test_spin_does_not_accept_client_results_identity_payment_or_expiry(
    extras_api, extra
):
    s = extras_api
    response = spin(s, extra=extra)
    assert response.status_code == 422 and "private" not in response.text
    assert not s.promotions.repo.state.spins and s.promotions.random.calls == 0


@pytest.mark.parametrize(
    "method,target,body",
    [
        ("get", "/api/v1/promotions/rewards", None),
        ("get", "/api/v1/promotions/roulette?branch_id={branch}", None),
        ("post", "/api/v1/promotions/roulette/spins", {"branch_id": "{branch}"}),
        ("get", "/api/v1/admin/promotions/branches/{branch}/roulette/campaigns", None),
    ],
)
def test_every_public_family_requires_auth(extras_api, method, target, body):
    s = extras_api
    branch = str(s.promotions.branch)
    response = s.client.request(
        method,
        target.format(branch=branch),
        json={k: v.format(branch=branch) for k, v in body.items()} if body else None,
        headers={"Idempotency-Key": "one"},
    )
    assert response.status_code == 401


def test_no_prize_snapshot_idempotent_no_reward(extras_api):
    s = extras_api
    s.promotions.random.value = 9999
    response = spin(s)
    assert response.status_code == 201 and response.json()["outcome"] == "NO_PRIZE"
    assert response.json()["prize"] is response.json()["reward"] is None
    s.promotions.random.value = 0
    assert spin(s).json() == response.json()
    assert s.client.get("/api/v1/promotions/rewards", headers=s.headers()).json() == []


def test_all_admin_configuration_routes_draft_activation_detail_patch_soft_deactivate(
    extras_api,
):
    s = extras_api
    header = s.headers("admin")
    body = {
        "name": "Draft",
        "terms_text": "Free",
        "starts_at": NOW.isoformat(),
        "spin_cooldown_seconds": 0,
    }
    draft = s.client.post(campaigns(s), json=body, headers=header)
    assert draft.status_code == 201
    id_ = draft.json()["id"]
    target = campaigns(s) + "/" + id_
    assert s.client.get(target, headers=header).json()["prizes"] == []
    assert len(s.client.get(campaigns(s), headers=header).json()) == 2
    assert (
        s.client.patch(target, json={"is_active": True}, headers=header).status_code
        == 409
    )
    prize = s.client.post(
        target + "/prizes",
        json={
            "product_id": str(s.promotions.catalog.product.id),
            "display_name": "New prize",
            "probability_bps": 1000,
        },
        headers=header,
    )
    assert prize.status_code == 201
    assert (
        s.client.post(
            campaigns(s) + "/" + str(s.promotions.campaign.id) + "/deactivate",
            headers=header,
        ).status_code
        == 200
    )
    assert (
        s.client.patch(target, json={"is_active": True}, headers=header).status_code
        == 200
    )
    prize_path = target + "/prizes/" + prize.json()["id"]
    assert (
        s.client.patch(
            prize_path, json={"probability_bps": 500}, headers=header
        ).status_code
        == 200
    )
    assert s.client.delete(prize_path, headers=header).status_code == 204
    detail = s.client.get(target, headers=header).json()
    assert len(detail["prizes"]) == 1 and not detail["prizes"][0]["is_active"]
    assert (
        s.client.post(target + "/deactivate", headers=header).json()["is_active"]
        is False
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"is_active": None},
        {"name": None},
        {"name": " "},
        {"starts_at": None},
        {"spin_cooldown_seconds": -1},
        {"spin_cooldown_seconds": 1.0},
        {"max_spins_per_customer_per_day": 0},
        {"reward_validity_days": 0},
        {"version": 2},
        {"created_by_user_id": "private"},
        {"branch_id": "private"},
        {"starts_at": "2026-10-07T00:00:00"},
        {"ends_at": "2026-10-06T00:00:00Z"},
    ],
)
def test_admin_campaign_invalid_patch_nulls_times_server_fields(extras_api, body):
    s = extras_api
    response = s.client.patch(
        campaigns(s) + "/" + str(s.promotions.campaign.id),
        json=body,
        headers=s.headers("admin"),
    )
    assert response.status_code == 422 and "private" not in response.text
    assert (
        s.promotions.repo.state.campaigns[s.promotions.campaign.id]
        == s.promotions.campaign
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"awarded_count": 0},
        {"customer_id": "private"},
        {"probability_bps": 10001},
        {"probability_bps": True},
        {"probability_bps": 1.5},
        {"product_id": None},
        {"is_active": None},
        {"max_awards": -1},
        {"display_name": "<script>private</script>"},
    ],
)
def test_admin_prize_invalid_patch_fields(extras_api, body):
    s = extras_api
    target = (
        campaigns(s)
        + "/"
        + str(s.promotions.campaign.id)
        + "/prizes/"
        + str(s.promotions.prize.id)
    )
    response = s.client.patch(target, json=body, headers=s.headers("admin"))
    assert response.status_code == 422 and "private" not in response.text
    assert s.promotions.repo.state.prizes[s.promotions.prize.id] == s.promotions.prize


def test_live_permissions_revocation_scope_and_signed_forged_role_claims_not_authority(
    extras_api,
):
    s = extras_api
    assert s.client.get(campaigns(s), headers=s.headers("kitchen")).status_code == 403
    # A cryptographically valid token carrying forged role/scope claims is still
    # authorized from current database-like authorization, not the claims.
    claims = jwt.decode(s.api.tokens["customer"], options={"verify_signature": False})
    claims.update(
        roles=["ADMIN"],
        permissions=["PROMOTION_MANAGE"],
        branch_id=str(s.promotions.branch),
    )
    signed = jwt.encode(
        claims,
        "notifications-tests-only-signing-key-at-least-32-characters",
        algorithm="HS256",
    )
    response = s.client.patch(
        campaigns(s) + "/" + str(s.promotions.campaign.id),
        json={"name": "Wrong"},
        headers={"Authorization": "Bearer " + signed},
    )
    assert response.status_code == 403
    s.promotions.authorization.permissions.remove("PROMOTION_MANAGE")
    assert s.client.get(campaigns(s), headers=s.headers("admin")).status_code == 200
    assert (
        s.client.post(
            campaigns(s) + "/" + str(s.promotions.campaign.id) + "/deactivate",
            headers=s.headers("admin"),
        ).status_code
        == 403
    )
    assert (
        s.client.get(
            "/api/v1/admin/promotions/branches/" + str(uuid4()) + "/roulette/campaigns",
            headers=s.headers("admin"),
        ).status_code
        == 403
    )
    user = s.api.auth.users[s.api.setup.customer.user_id]
    s.api.auth.users[user.id] = replace(user, account_status="BLOCKED")
    assert spin(s).status_code == 403


@pytest.mark.parametrize(
    "query", ["limit=101", "offset=-1", "customer_id=private", "status=private"]
)
def test_reward_query_extra_fields_forbidden(extras_api, query):
    s = extras_api
    response = s.client.get("/api/v1/promotions/rewards?" + query, headers=s.headers())
    assert response.status_code == 422 and "private" not in response.text
