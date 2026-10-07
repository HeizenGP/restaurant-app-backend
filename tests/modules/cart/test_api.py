import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.auth.application.repository import CustomerIdentityData, UserData
from app.modules.auth.application.services import AuthService
from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.auth.infrastructure.security.otp import HmacOtpCodeService
from app.modules.auth.infrastructure.security.otp_sender import InMemoryOtpSender
from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)
from app.modules.auth.infrastructure.security.refresh_tokens import (
    Sha256RefreshTokenHasher,
)
from app.modules.auth.infrastructure.security.tokens import PyJwtTokenService
from app.modules.auth.presentation.dependencies import get_auth_service
from app.modules.cart.presentation.dependencies import get_cart_service
from app.modules.catalog.application.dtos import BranchProductConfig, CatalogChanges
from app.shared.application.exceptions import DependencyUnavailableError
from app.shared.domain.time import utc_now
from app.shared.infrastructure.config.settings import Settings
from tests.modules.auth.fakes import MemoryAuthRepository
from tests.modules.cart.fakes import CartSetup

PREFIX = "/api/v1/cart"


@dataclass
class CartApi:
    client: TestClient
    setup: CartSetup
    auth: MemoryAuthRepository
    tokens: dict[str, str] = field(repr=False)

    def headers(self, who: str = "guest") -> dict[str, str]:
        return {"Authorization": "Bearer " + self.tokens[who]}

    def create(self, who: str = "guest"):
        return self.client.post(
            PREFIX,
            headers=self.headers(who),
            json={"branch_id": str(self.setup.branch)},
        )

    def body(self):
        return {
            "product_id": str(self.setup.product.id),
            "presentation_id": str(self.setup.personal.id),
            "quantity": 2,
        }

    def add(self, who: str = "guest", **values):
        return self.client.post(
            PREFIX + "/items", headers=self.headers(who), json=self.body() | values
        )


@pytest.fixture
def api(setup: CartSetup) -> Iterator[CartApi]:
    auth = MemoryAuthRepository()
    tokens_service = PyJwtTokenService(
        secret="cart-tests-only-signing-key-with-at-least-32-characters",
        algorithm="HS256",
        issuer="cart-tests",
        audience="cart-tests",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=1),
        phone_verification_ttl=timedelta(minutes=5),
    )
    hasher = PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    dummy_hash = hasher.hash_password("cart-tests-only-dummy")
    tokens = {}
    for index, (name, principal) in enumerate(
        (
            ("guest", setup.guest),
            ("registered", setup.registered),
            (
                "other",
                Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4()),
            ),
            (
                "staff",
                Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4()),
            ),
        )
    ):
        if principal.user_id:
            auth.users[principal.user_id] = UserData(
                id=principal.user_id,
                phone=None,
                email=name + "@example.test",
                first_name="Test",
                last_name=None,
                password_hash=dummy_hash,
                account_status="ACTIVE",
                phone_verified_at=None,
                deleted_at=None,
            )
        if principal.customer_id:
            auth.customers[principal.customer_id] = CustomerIdentityData(
                id=principal.customer_id,
                user_id=principal.user_id,
                full_name=name,
                phone="+5199999910" + str(index),
                email=None,
                phone_verified_at=utc_now(),
            )
        tokens[name] = tokens_service.create_access_token(principal)
    asyncio.run(auth.commit())
    service = AuthService(
        repository=auth,
        password_hasher=hasher,
        token_service=tokens_service,
        refresh_token_hasher=Sha256RefreshTokenHasher(),
        otp_codes=HmacOtpCodeService(pepper="cart-tests-only-pepper"),
        otp_sender=InMemoryOtpSender(environment="test"),
        dummy_password_hash=dummy_hash,
        access_expires_seconds=900,
        otp_expires=timedelta(minutes=5),
        otp_max_attempts=3,
        otp_resend_cooldown=timedelta(seconds=60),
        expose_debug_otp=True,
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_auth_service] = lambda: service
    app.dependency_overrides[get_cart_service] = lambda: setup.service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield CartApi(client, setup, auth, tokens)


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", ""),
        ("get", ""),
        ("delete", ""),
        ("post", "/items"),
        ("patch", "/items/00000000-0000-0000-0000-000000000001"),
        ("delete", "/items/00000000-0000-0000-0000-000000000001"),
        ("post", "/recalculate"),
    ],
)
def test_all_cart_operations_require_existing_authentication(
    api: CartApi, method, path
):
    assert getattr(api.client, method)(PREFIX + path).status_code == 401


@pytest.mark.parametrize("who", ["guest", "registered"])
def test_http_cart_lifecycle_and_decimal_totals(api: CartApi, who):
    assert api.client.get(PREFIX, headers=api.headers(who)).status_code == 404
    cart = api.create(who)
    assert cart.status_code == 201, cart.text
    assert cart.json()["status"] == "ACTIVE" and cart.json()["total"] == "0.00"
    assert api.create(who).status_code == 409
    item = api.add(who, notes=" Sin cebolla ")
    assert item.status_code == 201, item.text
    data = item.json()
    assert data["line_total"] == "40.00" and data["notes"] == "Sin cebolla"
    assert "customer_id" not in data and "branch_id" not in data
    updated = api.client.patch(
        PREFIX + "/items/" + data["id"], headers=api.headers(who), json={"quantity": 3}
    )
    assert updated.status_code == 200 and updated.json()["notes"] == "Sin cebolla"
    view = api.client.get(PREFIX, headers=api.headers(who)).json()
    assert view["subtotal"] == view["total"] == "60.00"
    assert (
        view["charges_total"] == view["discount_total"] == "0.00"
        and view["item_count"] == 3
    )
    assert (
        api.client.post(PREFIX + "/recalculate", headers=api.headers(who)).status_code
        == 200
    )
    assert (
        api.client.delete(
            PREFIX + "/items/" + data["id"], headers=api.headers(who)
        ).status_code
        == 204
    )
    assert api.client.get(PREFIX, headers=api.headers(who)).json()["items"] == []
    assert api.client.delete(PREFIX, headers=api.headers(who)).status_code == 204
    assert api.client.get(PREFIX, headers=api.headers(who)).status_code == 404
    assert api.create(who).status_code == 201


@pytest.mark.parametrize(
    "field",
    [
        "customer_id",
        "cart_id",
        "branch_id",
        "id",
        "created_at",
        "updated_at",
        "product_id",
        "base_price",
        "unit_price",
        "unit_price_snapshot",
        "additional_price",
        "line_total",
        "subtotal",
        "total",
        "charge",
        "discount",
        "roles",
        "permissions",
    ],
)
def test_requests_reject_mass_assignment_and_frontend_money(api: CartApi, field):
    api.create()
    if field == "product_id":
        response = api.client.patch(
            PREFIX + "/items/" + str(uuid4()),
            headers=api.headers(),
            json={field: str(uuid4())},
        )
    else:
        response = api.add(**{field: "1"})
    assert response.status_code == 422
    assert not api.setup.repository.items


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"quantity": 0},
        {"quantity": -1},
        {"quantity": True},
        {"quantity": 1.2},
        {"quantity": "2"},
        {"quantity": 10001},
        {"quantity": None},
        {"notes": "x" * 1001},
        {"presentation_id": None},
        {"addons": None},
    ],
)
def test_invalid_patch_returns_422_and_preserves_item(api: CartApi, changes):
    api.create()
    item = api.add().json()
    response = api.client.patch(
        PREFIX + "/items/" + item["id"], headers=api.headers(), json=changes
    )
    assert response.status_code == 422, response.text
    assert api.client.get(PREFIX, headers=api.headers()).json()["items"][0] == item


def test_http_patch_clears_notes_and_optional_addons_and_changes_presentation(
    api: CartApi,
):
    api.create()
    addons = [
        {
            "addon_id": str(api.setup.addon.id),
            "option_ids": [str(api.setup.free.id), str(api.setup.paid.id)],
        }
    ]
    item = api.add(notes="Sin cebolla", addons=addons).json()
    assert item["addons_price_snapshot"] == "3.50"
    assert len(item["selected_options"]) == 2
    response = api.client.patch(
        PREFIX + "/items/" + item["id"],
        headers=api.headers(),
        json={
            "notes": None,
            "addons": [],
            "presentation_id": str(api.setup.family.id),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["notes"] is None and not response.json()["selected_options"]
    assert response.json()["unit_price_snapshot"] == "35.00"


def test_query_parameters_never_override_current_identity(api: CartApi):
    api.create()
    for name in ("customer_id", "cart_id", "branch_id"):
        assert (
            api.client.get(
                PREFIX, headers=api.headers(), params={name: str(uuid4())}
            ).status_code
            == 422
        )


def test_idor_hides_foreign_items_and_abandon_never_affects_other_cart(api: CartApi):
    api.create()
    own = api.add().json()
    api.create("other")
    foreign = api.add("other").json()
    path = PREFIX + "/items/" + foreign["id"]
    for response in (
        api.client.patch(path, headers=api.headers(), json={"quantity": 4}),
        api.client.delete(path, headers=api.headers()),
    ):
        assert (
            response.status_code == 404
            and response.json()["error"]["code"] == "CART_ITEM_NOT_FOUND"
        )
    assert api.client.delete(PREFIX, headers=api.headers()).status_code == 204
    assert (
        api.client.get(PREFIX, headers=api.headers("other")).json()["items"][0]["id"]
        == foreign["id"]
    )
    assert UUID(own["id"]) in api.setup.repository.items


@pytest.mark.parametrize("state", ["BLOCKED", "DISABLED", "DELETED"])
def test_current_account_state_rejects_registered_token(api: CartApi, state):
    user = api.auth.users[api.setup.registered.user_id]
    api.auth.users[user.id] = (
        replace(user, deleted_at=utc_now())
        if state == "DELETED"
        else replace(user, account_status=state)
    )
    assert api.create("registered").status_code in {401, 403}
    assert not api.setup.repository.carts


def test_invalid_tokens_and_non_customer_staff_cannot_create_cart(api: CartApi):
    assert (
        api.client.post(
            PREFIX,
            headers={"Authorization": "Bearer broken"},
            json={"branch_id": str(api.setup.branch)},
        ).status_code
        == 401
    )
    assert api.create("staff").status_code == 401


def test_http_get_retains_price_and_recalculate_is_explicit(api: CartApi):
    api.create()
    item = api.add().json()
    asyncio.run(
        api.setup.catalog.update_product(
            api.setup.admin,
            api.setup.product.id,
            CatalogChanges({"base_price": Decimal("22")}),
        )
    )
    assert api.client.get(PREFIX, headers=api.headers()).json()["items"][0] == item
    result = api.client.post(PREFIX + "/recalculate", headers=api.headers())
    assert result.status_code == 200 and result.json()["total"] == "44.00"


def test_http_sold_out_prevents_add_and_recalculate_does_not_delete_items(api: CartApi):
    api.create()
    item = api.add().json()
    asyncio.run(
        api.setup.catalog.upsert_branch_product(
            api.setup.admin,
            api.setup.branch,
            api.setup.product.id,
            BranchProductConfig(False, None),
        )
    )
    response = api.add()
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "CART_PRODUCT_UNAVAILABLE"
    )
    response = api.client.post(PREFIX + "/recalculate", headers=api.headers())
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "CART_RECALCULATION_FAILED"
    )
    assert api.client.get(PREFIX, headers=api.headers()).json()["items"][0] == item


def test_real_guest_registration_keeps_cart_without_auth_changes(api: CartApi):
    api.create()
    item = api.add().json()
    phone = api.auth.customers[api.setup.guest.customer_id].phone
    requested = api.client.post(
        "/api/v1/auth/otp/request", json={"phone": phone, "purpose": "REGISTER"}
    )
    assert requested.status_code == 202, requested.text
    verified = api.client.post(
        "/api/v1/auth/otp/verify",
        json={
            "phone": phone,
            "purpose": "REGISTER",
            "code": requested.json()["debug_code"],
        },
    )
    assert verified.status_code == 200, verified.text
    registered = api.client.post(
        "/api/v1/auth/register",
        json={
            "verification_token": verified.json()["verification_token"],
            "first_name": "Guest",
            "password": "test-only-registration-password",
        },
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": "Bearer " + registered.json()["access_token"]}
    result = api.client.get(PREFIX, headers=headers)
    assert result.status_code == 200 and result.json()["items"][0]["id"] == item["id"]
    assert api.auth.customers[api.setup.guest.customer_id].user_id is not None
    assert api.client.get(PREFIX, headers=api.headers()).status_code == 401


def test_dependency_unavailability_keeps_existing_503_envelope(api: CartApi):
    async def unavailable(principal):
        raise DependencyUnavailableError("Database is unavailable")

    api.setup.service.get_cart = unavailable
    result = api.client.get(PREFIX, headers=api.headers())
    assert result.status_code == 503
    assert result.json() == {
        "error": {
            "code": "DEPENDENCY_UNAVAILABLE",
            "message": "Database is unavailable",
        }
    }


def test_openapi_has_seven_customer_operations_and_no_admin_cart(api: CartApi):
    schema = api.client.get("/openapi.json").json()
    operations = [
        operation
        for path, details in schema["paths"].items()
        if path.startswith(PREFIX)
        for method, operation in details.items()
        if method in {"get", "post", "patch", "delete"}
    ]
    assert len(operations) == 7
    assert all(
        operation["tags"] == ["cart"] and operation["security"]
        for operation in operations
    )
    assert not any("admin/cart" in path for path in schema["paths"])


@pytest.mark.parametrize(
    "method,path", [("delete", ""), ("delete", "/items/"), ("post", "/recalculate")]
)
def test_operations_without_body_reject_identity_and_price_injection(
    api: CartApi, method, path
):
    api.create()
    item = api.add().json()
    if path == "/items/":
        path += item["id"]
    response = api.client.request(
        method,
        PREFIX + path,
        headers=api.headers(),
        json={"cart_id": str(uuid4()), "total": "0.00"},
    )
    assert response.status_code == 422
    assert api.client.get(PREFIX, headers=api.headers()).json()["items"][0] == item


def test_nested_addon_prices_cannot_be_supplied_by_frontend(api: CartApi):
    api.create()
    response = api.add(
        addons=[
            {
                "addon_id": str(api.setup.addon.id),
                "option_ids": [str(api.setup.paid.id)],
                "additional_price": "0.00",
            }
        ]
    )
    assert response.status_code == 422 and not api.setup.repository.items
