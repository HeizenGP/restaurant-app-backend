from uuid import uuid4

import pytest

from tests.modules.notifications.fakes import enqueue, notification


@pytest.mark.parametrize("resource", ["review", "receipt", "notification", "rewards"])
def test_customer_b_cannot_read_or_mutate_customer_a_resource(extras_api, resource):
    s = extras_api
    if resource == "review":
        order = s.reviews.orders.order.id
        target = f"/api/v1/orders/{order}/review"
        assert (
            s.client.post(target, headers=s.headers(), json={"rating": 5}).status_code
            == 201
        )
        assert s.client.get(target, headers=s.headers("foreign")).status_code == 404
        assert (
            s.client.post(
                target, headers=s.headers("foreign"), json={"rating": 1}
            ).status_code
            == 404
        )
    elif resource == "receipt":
        target = f"/api/v1/orders/{s.receipts.orders.order.id}/receipt"
        assert (
            s.client.post(
                target,
                headers=s.headers(**{"Idempotency-Key": "receipt"}),
                json={"document_type": "BOLETA"},
            ).status_code
            == 201
        )
        assert s.client.get(target, headers=s.headers("foreign")).status_code == 404
    elif resource == "notification":
        n = notification(s.api.setup.customer.customer_id, s.api.setup.branch)
        enqueue(s.api.setup.store, n)
        assert (
            s.client.post(
                f"/api/v1/notifications/{n.id}/read", headers=s.headers("foreign")
            ).status_code
            == 404
        )
    else:
        result = s.client.post(
            "/api/v1/promotions/roulette/spins",
            json={"branch_id": str(s.promotions.branch)},
            headers=s.headers(**{"Idempotency-Key": "spin"}),
        )
        assert result.status_code == 201 and result.json()["reward"]
        assert (
            s.client.get(
                "/api/v1/promotions/rewards", headers=s.headers("foreign")
            ).json()
            == []
        )


@pytest.mark.parametrize("family", ["reviews", "receipts", "promotions", "realtime"])
def test_branch_a_admin_cannot_access_branch_b_routes(extras_api, family):
    s = extras_api
    foreign_branch = uuid4()
    targets = {
        "reviews": f"/api/v1/admin/reviews/branches/{foreign_branch}",
        "receipts": f"/api/v1/admin/receipts/branches/{foreign_branch}",
        "promotions": (
            f"/api/v1/admin/promotions/branches/{foreign_branch}/roulette/campaigns"
        ),
        "realtime": f"/api/v1/admin/realtime/branches/{foreign_branch}/orders/events",
    }
    assert s.client.get(targets[family], headers=s.headers("admin")).status_code == 403


def test_admin_cannot_modify_foreign_campaign_or_process_foreign_receipt(extras_api):
    s = extras_api
    branch = s.api.setup.branch
    response = s.client.patch(
        f"/api/v1/admin/promotions/branches/{branch}/roulette/campaigns/{uuid4()}",
        headers=s.headers("admin"),
        json={"name": "TEST foreign"},
    )
    assert response.status_code == 404
    response = s.client.post(
        f"/api/v1/admin/receipts/branches/{branch}/{uuid4()}/process",
        headers=s.headers("admin", **{"Idempotency-Key": "foreign"}),
    )
    assert response.status_code == 404
