import asyncio
from uuid import uuid4

import pytest

from app.modules.kitchen.application.errors import KitchenIntegrityError
from app.modules.kitchen.application.services import KitchenService
from app.modules.kitchen.presentation.dependencies import get_kitchen_service
from app.modules.orders.domain.models import OrderMode, OrderStatus
from app.modules.orders.presentation.dependencies import (
    get_order_service,
    get_order_settings_service,
)
from app.shared.application.exceptions import DependencyUnavailableError
from tests.modules.kitchen.conftest import block_user
from tests.modules.kitchen.fakes import NOW, record


def endpoints(api):
    return (
        ("get", api.base + "/queue"),
        ("get", api.order_path),
        ("post", api.order_path + "/start-preparation"),
        ("post", api.order_path + "/mark-ready"),
    )


@pytest.mark.parametrize("index", range(4))
def test_every_endpoint_requires_real_authentication(api, index):
    method, url = endpoints(api)[index]
    response = getattr(api.client, method)(url)
    assert response.status_code == 401


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("who", ["guest", "customer", "foreign"])
def test_no_staff_permission_means_forbidden_not_role_claims(api, index, who):
    method, url = endpoints(api)[index]
    response = getattr(api.client, method)(url, headers=api.headers(who))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "KITCHEN_PERMISSION_DENIED"


@pytest.mark.parametrize("who", ["kitchen", "admin"])
def test_authorized_staff_can_read_but_not_another_branch(api, who):
    assert (
        api.client.get(api.base + "/queue", headers=api.headers(who)).status_code == 200
    )
    url = api.base.replace(str(api.setup.branch), str(uuid4())) + "/queue"
    assert api.client.get(url, headers=api.headers(who)).status_code == 403


@pytest.mark.parametrize(
    "suffix,method",
    [("", "get"), ("/start-preparation", "post"), ("/mark-ready", "post")],
)
def test_branch_order_idor_returns_404(api, suffix, method):
    row = api.setup.store.add(record(branch_id=uuid4()))
    url = api.base + "/orders/" + str(row.id) + suffix
    assert getattr(api.client, method)(url, headers=api.headers()).status_code == 404


def test_full_workflow_retry_history_and_actor_are_server_controlled(api):
    start = api.client.post(
        api.order_path + "/start-preparation", headers=api.headers(), json={}
    )
    assert start.status_code == 200 and start.json()["status"] == "PREPARING"
    repeat = api.client.post(
        api.order_path + "/start-preparation", headers=api.headers()
    )
    assert repeat.status_code == 200 and len(repeat.json()["history"]) == 2
    ready = api.client.post(api.order_path + "/mark-ready", headers=api.headers())
    assert ready.status_code == 200 and ready.json()["status"] == "READY"
    repeat = api.client.post(
        api.order_path + "/mark-ready", headers=api.headers("admin")
    )
    assert repeat.status_code == 200 and len(repeat.json()["history"]) == 3
    assert [entry["to_status"] for entry in repeat.json()["history"]] == [
        "WAITING",
        "PREPARING",
        "READY",
    ]
    assert all(
        entry.changed_by_user_id == api.setup.user.user_id
        for entry in api.setup.row.history[1:]
    )
    assert (
        api.client.post(
            api.order_path + "/start-preparation", headers=api.headers()
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "mode,target",
    [
        (OrderMode.LOCAL, "READY"),
        (OrderMode.DELIVERY, "READY"),
        (OrderMode.PICKUP, "READY_FOR_PICKUP"),
    ],
)
def test_ready_response_mode_mapping(api, mode, target):
    row = api.setup.store.add(
        record(branch_id=api.setup.branch, mode=mode, status=OrderStatus.PREPARING)
    )
    url = api.base + "/orders/" + str(row.id) + "/mark-ready"
    response = api.client.post(url, headers=api.headers())
    assert response.status_code == 200 and response.json()["status"] == target
    assert response.json()["mode"] == mode.value


@pytest.mark.parametrize("mode", list(OrderMode))
def test_cards_minimize_sensitive_and_financial_data(api, mode):
    row = api.setup.store.add(record(branch_id=api.setup.branch, mode=mode))
    url = api.base + "/orders/" + str(row.id)
    response = api.client.get(url, headers=api.headers())
    assert response.status_code == 200
    card = response.json()
    forbidden = {
        "customer_id",
        "customer_email",
        "customer_name_snapshot",
        "customer_phone_snapshot",
        "pickup_phone_snapshot",
        "pickup_name_snapshot",
        "recipient_phone_snapshot",
        "recipient_name_snapshot",
        "address_line_snapshot",
        "district_snapshot",
        "latitude_snapshot",
        "longitude_snapshot",
        "subtotal",
        "total",
        "delivery_fee",
        "charges_total",
        "discount_total",
        "unit_price_snapshot",
        "additional_price_snapshot",
        "payment_status",
        "payment_method_type",
        "qr_token",
        "idempotency_key",
        "request_fingerprint",
        "changed_by_user_id",
    }

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(child) for child in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(child) for child in value))
        return set()

    assert not keys(card) & forbidden
    assert card["items"][0]["notes"] == "Sin cebolla"
    assert (
        card["items"][0]["addon_options"][0]["option_name_snapshot"]
        == "Wantán original"
    )
    assert card["timing"]["waiting_seconds"] == 1200
    assert card["confirmed_at"] != card["created_at"]
    assert card["generated_at"].endswith("Z")


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "CANCELLED"),
        ("actor", "fake"),
        ("changed_by_user_id", str(uuid4())),
        ("branch_id", str(uuid4())),
        ("timestamp", "2026-10-06"),
        ("reason", "fake"),
        ("payment_status", "PAID"),
    ],
)
@pytest.mark.parametrize("suffix", ["/start-preparation", "/mark-ready"])
def test_command_payload_cannot_choose_status_or_actor(api, field, value, suffix):
    response = api.client.post(
        api.order_path + suffix, headers=api.headers(), json={field: value}
    )
    assert response.status_code == 422
    assert api.setup.store.transitions == 0
    assert value not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "?status=CANCELLED",
        "?status=PENDING_PAYMENT",
        "?status=SCHEDULED",
        "?mode=BAD",
        "?limit=0",
        "?limit=201",
        "?offset=-1",
        "?offset=100001",
        "?arbitrary=true",
    ],
)
def test_queue_validates_bounded_safe_filters(api, query):
    assert (
        api.client.get(api.base + "/queue" + query, headers=api.headers()).status_code
        == 422
    )


def test_queue_grouping_pagination_and_gets_never_write(api):
    api.setup.store.add(
        record(branch_id=api.setup.branch, status=OrderStatus.PREPARING, number=2)
    )
    api.setup.store.add(
        record(
            branch_id=api.setup.branch,
            mode=OrderMode.PICKUP,
            status=OrderStatus.READY_FOR_PICKUP,
            number=3,
        )
    )
    result = api.client.get(api.base + "/queue", headers=api.headers())
    assert result.status_code == 200
    queue = result.json()
    assert len(queue["waiting"]) == len(queue["preparing"]) == len(queue["ready"]) == 1
    assert "history" not in queue["waiting"][0]
    page = api.client.get(
        api.base + "/queue?limit=1&offset=1", headers=api.headers()
    ).json()
    assert len(page["preparing"]) == 1 and page["has_more"]
    assert api.setup.store.commits == api.setup.store.transitions == 0


def test_permissions_are_rechecked_without_token_reissue(api):
    assert api.client.get(api.base + "/queue", headers=api.headers()).status_code == 200
    api.setup.authorization.grants.clear()
    assert api.client.get(api.base + "/queue", headers=api.headers()).status_code == 403


def test_blocked_account_invalidates_existing_jwt_using_standard_auth_policy(api):
    block_user(api, "kitchen")
    assert api.client.get(api.base + "/queue", headers=api.headers()).status_code == 403


def test_missing_history_is_safe_503_not_fabricated_time(api):
    api.setup.row.history = ()
    response = api.client.get(api.order_path, headers=api.headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == KitchenIntegrityError.code


def test_dependency_unavailable_is_safe_503(api):
    class Unavailable:
        async def queue(self, *args):
            raise DependencyUnavailableError("Database is unavailable")

    service = KitchenService(Unavailable(), api.setup.authorization, clock=lambda: NOW)
    api.client.app.dependency_overrides[get_kitchen_service] = lambda: service
    response = api.client.get(api.base + "/queue", headers=api.headers())
    assert response.status_code == 503
    assert "sql" not in response.text.lower()


def test_actual_session_boundary_sanitizes_database_connection_failure(api):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import OperationalError

    store = AsyncMock()
    store.execute.side_effect = OperationalError(
        "private SQL", {"secret": "private payload"}, Exception("private DSN")
    )

    @asynccontextmanager
    async def factory():
        yield store

    del api.client.app.dependency_overrides[get_kitchen_service]
    api.client.app.state.session_factory = factory
    response = api.client.get(api.base + "/queue", headers=api.headers())
    assert response.status_code == 503
    assert "private" not in response.text
    store.rollback.assert_awaited_once()


def test_no_generic_status_cancel_payment_or_fulfillment_routes(api):
    paths = api.client.get("/openapi.json").json()["paths"]
    kitchen = {path for path in paths if "/kitchen/" in path}
    assert len(kitchen) == 4
    assert {method for path in kitchen for method in paths[path]} == {"get", "post"}
    for suffix in (
        "/cancel",
        "/mark-paid",
        "/served",
        "/picked-up",
        "/out-for-delivery",
        "/delivered",
    ):
        assert (
            api.client.post(api.order_path + suffix, headers=api.headers()).status_code
            == 404
        )
    assert (
        api.client.patch(
            api.order_path, headers=api.headers(), json={"status": "CANCELLED"}
        ).status_code
        == 405
    )


def test_kitchen_grants_do_not_allow_cash_release_or_order_settings(api):
    from tests.modules.orders.fakes import orders_setup

    orders = asyncio.run(orders_setup())
    order = asyncio.run(
        orders.service.create(orders.cart.guest, "permission-test", orders.local())
    )
    api.client.app.dependency_overrides[get_order_service] = lambda: orders.service
    api.client.app.dependency_overrides[get_order_settings_service] = lambda: (
        orders.admin_service
    )
    response = api.client.post(
        "/api/v1/admin/orders/" + str(order.id) + "/confirm-cash-release",
        headers=api.headers(),
    )
    assert response.status_code == 403
    response = api.client.get(
        "/api/v1/admin/orders/branches/" + str(orders.cart.branch) + "/settings",
        headers=api.headers(),
    )
    assert response.status_code == 403
