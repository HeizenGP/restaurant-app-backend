import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.auth.application.repository import CustomerIdentityData, UserData
from app.modules.auth.application.services import AuthService
from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.auth.infrastructure.security.otp import HmacOtpCodeService
from app.modules.auth.infrastructure.security.passwords import (
    PwdlibArgon2PasswordHasher,
)
from app.modules.auth.infrastructure.security.refresh_tokens import (
    Sha256RefreshTokenHasher,
)
from app.modules.auth.infrastructure.security.tokens import PyJwtTokenService
from app.modules.auth.presentation.dependencies import get_auth_service
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.presentation.dependencies import get_catalog_service
from app.shared.domain.time import utc_now
from app.shared.infrastructure.config.settings import Settings
from tests.modules.auth.fakes import MemoryAuthRepository
from tests.modules.catalog.fakes import (
    MemoryCatalogAuthorization,
    MemoryCatalogRepository,
    seed,
)

ADMIN = "/api/v1/admin/catalog"


@dataclass
class CatalogApi:
    client: TestClient
    headers: dict[str, str]
    tokens: dict[str, str]
    auth: MemoryAuthRepository
    repository: MemoryCatalogRepository
    authorization: MemoryCatalogAuthorization
    actor: Principal
    branch_a: UUID
    branch_b: UUID


@pytest.fixture
def api(
    catalog_service: CatalogService,
    catalog_repository,
    authorization,
    admin,
    branch_a,
    branch_b,
) -> Iterator[CatalogApi]:
    auth_repository = MemoryAuthRepository()
    token_service = PyJwtTokenService(
        secret="catalog-tests-only-signing-secret-not-real-credentials",
        algorithm="HS256",
        issuer="catalog-tests",
        audience="catalog-tests",
        access_ttl=timedelta(minutes=15),
        refresh_ttl=timedelta(days=1),
        phone_verification_ttl=timedelta(minutes=5),
    )
    hasher = PwdlibArgon2PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    tokens: dict[str, str] = {}
    for name, principal in (
        ("admin", admin),
        (
            "customer",
            Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4()),
        ),
        ("staff", Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())),
        ("guest", Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())),
    ):
        if principal.user_id is not None:
            auth_repository.users[principal.user_id] = UserData(
                id=principal.user_id,
                phone=None,
                email=f"{name}@example.test",
                first_name="Test",
                last_name=None,
                password_hash="test-only-not-used",
                account_status="ACTIVE",
                phone_verified_at=None,
                deleted_at=None,
            )
        else:
            auth_repository.customers[principal.customer_id] = CustomerIdentityData(
                id=principal.customer_id,
                user_id=None,
                full_name="Guest",
                phone="+51999999001",
                email=None,
                phone_verified_at=utc_now(),
            )
        tokens[name] = token_service.create_access_token(principal)
    auth_service = AuthService(
        repository=auth_repository,
        password_hasher=hasher,
        token_service=token_service,
        refresh_token_hasher=Sha256RefreshTokenHasher(),
        otp_codes=HmacOtpCodeService(pepper="catalog-test-only-pepper"),
        otp_sender=None,
        dummy_password_hash=hasher.hash_password("test-only-dummy"),
        access_expires_seconds=900,
        otp_expires=timedelta(minutes=5),
        otp_max_attempts=3,
        otp_resend_cooldown=timedelta(seconds=60),
        expose_debug_otp=False,
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service
    with TestClient(app, raise_server_exceptions=False) as client:
        yield CatalogApi(
            client,
            {"Authorization": f"Bearer {tokens['admin']}"},
            tokens,
            auth_repository,
            catalog_repository,
            authorization,
            admin,
            branch_a,
            branch_b,
        )


def setup_product(api: CatalogApi) -> tuple[str, str]:
    category = api.client.post(
        f"{ADMIN}/categories",
        headers=api.headers,
        json={"name": "Arroces", "slug": "arroces"},
    )
    assert category.status_code == 201, category.text
    product = api.client.post(
        f"{ADMIN}/products",
        headers=api.headers,
        json={
            "category_id": category.json()["id"],
            "name": "Aeropuerto",
            "slug": "aeropuerto",
            "base_price": "20.00",
        },
    )
    assert product.status_code == 201, product.text
    return category.json()["id"], product.json()["id"]


def test_public_menu_is_anonymous_and_requires_branch(api: CatalogApi):
    assert api.client.get("/api/v1/catalog/menu").status_code == 422
    assert (
        api.client.get(
            "/api/v1/catalog/menu", params={"branch_id": "invalid"}
        ).status_code
        == 422
    )
    assert (
        api.client.get(
            "/api/v1/catalog/menu", params={"branch_id": str(api.branch_a)}
        ).json()
        == []
    )
    assert (
        api.client.get(
            "/api/v1/catalog/menu", params={"branch_id": str(uuid4())}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "who,status",
    [
        ("missing", 401),
        ("bad-jwt", 401),
        ("guest", 403),
        ("customer", 403),
        ("staff", 403),
        ("admin", 200),
    ],
)
def test_admin_security_uses_existing_bearer_and_token_validation(
    api: CatalogApi, who: str, status: int
):
    headers = (
        {}
        if who == "missing"
        else {"Authorization": f"Bearer {api.tokens.get(who, 'invalid-token')}"}
    )
    response = api.client.get(f"{ADMIN}/categories", headers=headers)
    assert response.status_code == status
    if status != 200:
        assert set(response.json()) == {"error"}


@pytest.mark.parametrize("status", ["BLOCKED", "DISABLED", "DELETED"])
def test_current_account_state_invalidates_old_access(api: CatalogApi, status: str):
    user = api.auth.users[api.actor.user_id]
    api.auth.users[user.id] = replace(
        user,
        account_status=status if status != "DELETED" else "ACTIVE",
        deleted_at=utc_now() if status == "DELETED" else None,
    )
    response = api.client.get(f"{ADMIN}/categories", headers=api.headers)
    assert response.status_code in {401, 403}


def test_revocation_ended_assignment_and_inactive_branch_apply_immediately(
    api: CatalogApi,
):
    grant = api.authorization.grants[api.actor.user_id][0]
    assert api.client.get(f"{ADMIN}/categories", headers=api.headers).status_code == 200
    grant.ended = True
    assert api.client.get(f"{ADMIN}/categories", headers=api.headers).status_code == 403
    grant.ended = False
    api.repository.branches.remove(api.branch_a)
    assert api.client.get(f"{ADMIN}/categories", headers=api.headers).status_code == 403


def test_http_menu_price_and_sold_out_not_hidden(
    api: CatalogApi, catalog_service: CatalogService
):
    asyncio.run(seed(catalog_service, api.actor))
    product_id = next(iter(api.repository.products))
    before = api.client.get(
        "/api/v1/catalog/menu", params={"branch_id": str(api.branch_a)}
    )
    assert (
        before.status_code == 200
        and before.json()[0]["products"][0]["effective_base_price"] == "20.00"
    )
    override = api.client.put(
        f"{ADMIN}/branches/{api.branch_a}/products/{product_id}",
        headers=api.headers,
        json={"is_available": False, "price_override": "22.00"},
    )
    assert override.status_code == 200
    detail = api.client.get(
        f"/api/v1/catalog/products/{product_id}",
        params={"branch_id": str(api.branch_a)},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["state"] == "SOLD_OUT" and not body["is_available"]
    assert body["presentations"][1]["effective_price"] == "37.00"
    assert "deleted_at" not in body and "password_hash" not in body
    other = api.client.put(
        f"{ADMIN}/branches/{api.branch_b}/products/{product_id}",
        headers=api.headers,
        json={"is_available": False},
    )
    assert other.status_code == 403


def test_category_product_update_archive_conflict_and_audit(api: CatalogApi):
    category_id, product_id = setup_product(api)
    assert api.client.get(f"{ADMIN}/products", headers=api.headers).status_code == 200
    assert (
        api.client.get(f"{ADMIN}/products/{product_id}", headers=api.headers).json()[
            "is_publicable"
        ]
        is False
    )
    updated = api.client.patch(
        f"{ADMIN}/categories/{category_id}",
        headers=api.headers,
        json={"name": "Arroces Chifa"},
    )
    assert updated.status_code == 200
    price = api.client.patch(
        f"{ADMIN}/products/{product_id}",
        headers=api.headers,
        json={"base_price": "23.50"},
    )
    assert price.status_code == 200 and price.json()["base_price"] == "23.50"
    rejected = api.client.delete(
        f"{ADMIN}/categories/{category_id}", headers=api.headers
    )
    assert (
        rejected.status_code == 409
        and rejected.json()["error"]["code"] == "CATEGORY_HAS_ACTIVE_PRODUCTS"
    )
    assert (
        api.client.delete(
            f"{ADMIN}/products/{product_id}", headers=api.headers
        ).status_code
        == 204
    )
    assert (
        api.client.delete(
            f"{ADMIN}/categories/{category_id}", headers=api.headers
        ).status_code
        == 204
    )
    actions = {event.action for event in api.repository.events}
    assert {
        "CATEGORY_CREATED",
        "CATEGORY_UPDATED",
        "PRODUCT_CREATED",
        "PRODUCT_UPDATED",
        "PRODUCT_ARCHIVED",
        "CATEGORY_ARCHIVED",
    } <= actions


@pytest.mark.parametrize(
    "resource,body,patch,prefix",
    [
        (
            "images",
            {"url": "https://example.test/photo.png", "is_primary": True},
            {"alt_text": "Comida"},
            "PRODUCT_IMAGE",
        ),
        (
            "presentations",
            {"name": "Grande", "price_delta": "5.00", "is_default": True},
            {"name": "Compartido"},
            "PRODUCT_PRESENTATION",
        ),
        (
            "addons",
            {"name": "Extras", "min_select": 0, "max_select": 2},
            {"max_select": 3},
            "PRODUCT_ADDON",
        ),
        (
            "options",
            {"name": "Salsa", "additional_price": "0.00"},
            {"additional_price": "1.50"},
            "PRODUCT_ADDON_OPTION",
        ),
    ],
)
def test_all_child_admin_crud_and_audit(
    api: CatalogApi, resource: str, body: dict, patch: dict, prefix: str
):
    _, product_id = setup_product(api)
    base = f"{ADMIN}/products/{product_id}"
    if resource == "options":
        addon = api.client.post(
            base + "/addons", headers=api.headers, json={"name": "Extras"}
        )
        assert addon.status_code == 201
        base += "/addons/" + addon.json()["id"]
    base += "/" + resource
    created = api.client.post(base, headers=api.headers, json=body)
    assert created.status_code == 201, created.text
    entity_id = created.json()["id"]
    updated = api.client.patch(base + "/" + entity_id, headers=api.headers, json=patch)
    assert updated.status_code == 200, updated.text
    archived = api.client.delete(base + "/" + entity_id, headers=api.headers)
    assert archived.status_code == 204 and not archived.content
    events = {e.action for e in api.repository.events}
    assert {prefix + "_CREATED", prefix + "_UPDATED", prefix + "_ARCHIVED"} <= events


@pytest.mark.parametrize(
    "payload",
    [
        {"base_price": "-1"},
        {"base_price": "NaN"},
        {"base_price": "1.001"},
        {"base_price": "10000000000.00"},
        {"name": "  "},
        {"name": "Bad\u0000"},
        {"slug": "invalid slug"},
        {"sort_order": -1},
        {"is_active": "true"},
        {"id": str(uuid4())},
        {"deleted_at": "2026-10-06T00:00:00Z"},
        {"permissions": ["CATALOG_MANAGE"]},
    ],
)
def test_invalid_product_payload_never_mass_assigns(api: CatalogApi, payload: dict):
    category_id, _ = setup_product(api)
    body = {
        "category_id": category_id,
        "name": "Otro",
        "slug": "otro",
        "base_price": "10",
    }
    body.update(payload)
    response = api.client.post(f"{ADMIN}/products", headers=api.headers, json=body)
    assert response.status_code == 422, response.text
    assert len(api.repository.products) == 1
    assert "input" not in str(response.json())


@pytest.mark.parametrize(
    "resource,payload",
    [
        ("images", {"url": "ftp://example.test/photo.png"}),
        ("images", {"url": "https://user:private@example.test/photo.png"}),
        ("presentations", {"name": "Large", "price_delta": "-1"}),
        ("addons", {"name": "Extras", "min_select": 3, "max_select": 1}),
        ("addons", {"name": "Extras", "max_select": 0}),
    ],
)
def test_invalid_child_payload(api: CatalogApi, resource: str, payload: dict):
    _, product_id = setup_product(api)
    response = api.client.post(
        f"{ADMIN}/products/{product_id}/{resource}", headers=api.headers, json=payload
    )
    assert response.status_code == 422
    assert "private" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"base_price": None},
        {"updated_at": "now"},
        {"actor_user_id": str(uuid4())},
    ],
)
def test_patch_rejects_empty_null_or_internal_fields(api: CatalogApi, payload: dict):
    _, product_id = setup_product(api)
    response = api.client.patch(
        f"{ADMIN}/products/{product_id}", headers=api.headers, json=payload
    )
    assert response.status_code == 422


def test_slug_conflict_is_safe_http_409(api: CatalogApi):
    setup_product(api)
    response = api.client.post(
        f"{ADMIN}/categories",
        headers=api.headers,
        json={"name": "Otro", "slug": "arroces"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CATEGORY_SLUG_CONFLICT"
    assert "constraint" not in response.text and "SQL" not in response.text


def test_parent_ownership_cannot_be_changed_via_body(api: CatalogApi):
    _, product_id = setup_product(api)
    response = api.client.post(
        f"{ADMIN}/products/{product_id}/images",
        headers=api.headers,
        json={
            "url": "https://example.test/image.png",
            "product_id": str(uuid4()),
        },
    )
    assert response.status_code == 422


def test_cross_product_paths_are_rejected_http(api: CatalogApi):
    category_id, first_id = setup_product(api)
    second = api.client.post(
        f"{ADMIN}/products",
        headers=api.headers,
        json={
            "category_id": category_id,
            "name": "Otro",
            "slug": "otro",
            "base_price": "1",
        },
    ).json()["id"]
    presentation = api.client.post(
        f"{ADMIN}/products/{first_id}/presentations",
        headers=api.headers,
        json={"name": "Large", "price_delta": "1"},
    ).json()["id"]
    response = api.client.patch(
        f"{ADMIN}/products/{second}/presentations/{presentation}",
        headers=api.headers,
        json={"name": "Attack"},
    )
    assert response.status_code == 404


def test_openapi_has_all_phase_two_routes_and_error_models(api: CatalogApi):
    schema = api.client.get("/openapi.json").json()
    paths = schema["paths"]
    operations = [
        operation
        for path, methods in paths.items()
        if path.startswith(("/api/v1/catalog", ADMIN))
        for method, operation in methods.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]
    assert len(operations) == 25
    assert paths["/api/v1/catalog/menu"]["get"].get("security") is None
    assert paths[ADMIN + "/categories"]["post"]["security"]
    for operation in operations:
        assert operation["responses"]["503"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")


def test_partial_addon_patch_uses_current_limits_and_returns_422(api: CatalogApi):
    _, product_id = setup_product(api)
    base = f"{ADMIN}/products/{product_id}/addons"
    created = api.client.post(
        base, headers=api.headers, json={"name": "Extras", "max_select": 1}
    )
    response = api.client.patch(
        base + "/" + created.json()["id"], headers=api.headers, json={"min_select": 2}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CATALOG_DATA"
