import asyncio
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.catalog.application.dtos import (
    AddonSelection,
    BranchProductConfig,
    CatalogChanges,
    CategoryCreate,
    ImageCreate,
    PresentationCreate,
    ProductCreate,
)
from app.modules.catalog.application.errors import (
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogPermissionDeniedError,
    InvalidCatalogDataError,
    InvalidSelectionError,
    ProductNotAvailableError,
)
from app.modules.catalog.domain.models import (
    CatalogRuleError,
    ProductState,
    effective_base_price,
    money,
    presentation_price,
    validate_selection_limits,
)
from app.shared.domain.time import utc_now
from tests.modules.catalog.fakes import seed

D = Decimal


@pytest.mark.parametrize(
    "value", [D("-1"), D("1.001"), D("NaN"), D("Infinity"), D("10000000000"), 1.5]
)
def test_money_rejects_invalid_values(value: object) -> None:
    with pytest.raises(CatalogRuleError):
        money(value)


def test_exact_decimal_prices_and_zero_override() -> None:
    assert effective_base_price(D("20.10"), None) == D("20.10")
    assert effective_base_price(D("20.10"), D("0")) == D("0.00")
    assert presentation_price(D("22"), D("15")) == D("37.00")
    assert presentation_price(D("0.10"), D("0.20")) == D("0.30")


@pytest.mark.parametrize("minimum,maximum", [(-1, 1), (0, 0), (2, 1)])
def test_addon_selection_limits(minimum: int, maximum: int) -> None:
    with pytest.raises(CatalogRuleError):
        validate_selection_limits(minimum, maximum)


def test_menu_prices_notes_free_paid_addons_and_sold_out_visibility(
    catalog_service, admin, branch_a, branch_b, catalog_repository
):
    async def scenario() -> None:
        category, product, personal, familiar, addon, free, paid = await seed(
            catalog_service, admin
        )
        menu = await catalog_service.menu(branch_a)
        assert len(menu) == 1 and menu[0].id == category.id
        view = menu[0].products[0]
        assert view.effective_base_price == D("20.00") and view.allows_notes
        assert view.state is ProductState.AVAILABLE and view.is_available
        assert [p.effective_price for p in view.presentations] == [
            D("20.00"),
            D("35.00"),
        ]
        assert view.default_presentation.id == personal.id
        assert {o.additional_price for o in view.addons[0].options} == {
            D("0.00"),
            D("3.50"),
        }
        await catalog_service.upsert_branch_product(
            admin, branch_a, product.id, BranchProductConfig(False, D("22.00"))
        )
        sold_out = (await catalog_service.menu(branch_a))[0].products[0]
        assert sold_out.state is ProductState.SOLD_OUT and not sold_out.is_available
        assert sold_out.presentations[1].effective_price == D("37.00")
        other = await catalog_service.product_detail(branch_b, product.id)
        assert other.effective_base_price == D("20.00") and other.is_available
        assert len(catalog_repository.products) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("product", "is_active", False),
        ("product", "deleted_at", "NOW"),
        ("category", "is_active", False),
        ("category", "deleted_at", "NOW"),
        ("presentation", "is_active", False),
        ("presentation", "deleted_at", "NOW"),
    ],
)
def test_public_hides_inactive_archived_or_incomplete_configuration(
    catalog_service, admin, branch_a, catalog_repository, target, field, value
):
    async def scenario() -> None:
        category, product, personal, familiar, *_ = await seed(catalog_service, admin)
        change = {field: utc_now() if value == "NOW" else value}
        if target == "product":
            catalog_repository.products[product.id] = replace(product, **change)
        elif target == "category":
            catalog_repository.categories[category.id] = replace(category, **change)
        else:
            for p in (personal, familiar):
                catalog_repository.presentations[p.id] = replace(p, **change)
        assert await catalog_service.menu(branch_a) == []
        with pytest.raises(CatalogNotFoundError):
            await catalog_service.product_detail(branch_a, product.id)

    asyncio.run(scenario())


def test_draft_product_requires_presentation_to_be_public(
    catalog_service, admin, branch_a
):
    async def scenario() -> None:
        category = await catalog_service.create_category(
            admin, CategoryCreate(name="Sopas", slug="sopas")
        )
        product = await catalog_service.create_product(
            admin,
            ProductCreate(
                category_id=category.id, name="Sopa", slug="sopa", base_price=D("10")
            ),
        )
        assert await catalog_service.menu(branch_a) == []
        assert (
            await catalog_service.admin_product(admin, product.id)
        ).presentations == ()
        await catalog_service.create_presentation(
            admin, product.id, PresentationCreate(name="Tazon", price_delta=D("0"))
        )
        assert (await catalog_service.menu(branch_a))[0].products[0].id == product.id

    asyncio.run(scenario())


def test_deterministic_menu_child_ordering_and_primary(
    catalog_service, admin, branch_a
):
    async def scenario() -> None:
        _, product, *_ = await seed(catalog_service, admin)
        category = await catalog_service.create_category(
            admin, CategoryCreate(name="Bebidas", slug="bebidas", sort_order=0)
        )
        drink = await catalog_service.create_product(
            admin,
            ProductCreate(
                category_id=category.id, name="Chicha", slug="chicha", base_price=D("5")
            ),
        )
        await catalog_service.create_presentation(
            admin, drink.id, PresentationCreate(name="Vaso", price_delta=D("0"))
        )
        second = await catalog_service.create_product(
            admin,
            ProductCreate(
                category_id=product.category_id,
                name="Chaufa",
                slug="chaufa",
                base_price=D("12"),
                sort_order=0,
            ),
        )
        await catalog_service.create_presentation(
            admin, second.id, PresentationCreate(name="Plato", price_delta=D("0"))
        )
        later = await catalog_service.create_image(
            admin,
            product.id,
            ImageCreate(url="https://example.test/b.png", sort_order=2),
        )
        first = await catalog_service.create_image(
            admin,
            product.id,
            ImageCreate(
                url="https://example.test/a.png", sort_order=1, is_primary=True
            ),
        )
        menu = await catalog_service.menu(branch_a)
        assert [category.name for category in menu] == ["Arroces", "Bebidas"]
        assert [p.name for p in menu[0].products] == ["Aeropuerto", "Chaufa"]
        view = await catalog_service.product_detail(branch_a, product.id)
        assert [image.id for image in view.images] == [first.id, later.id]
        assert view.primary_image.id == first.id

    asyncio.run(scenario())


def test_primary_and_default_are_atomic_and_preserved_on_unrelated_patch(
    catalog_service, admin, branch_a, catalog_repository
):
    async def scenario() -> None:
        _, product, personal, familiar, *_ = await seed(catalog_service, admin)
        first = await catalog_service.create_image(
            admin,
            product.id,
            ImageCreate(url="https://example.test/a.png", is_primary=True),
        )
        second = await catalog_service.create_image(
            admin,
            product.id,
            ImageCreate(url="https://example.test/b.png", is_primary=True),
        )
        assert not catalog_repository.images[first.id].is_primary
        await catalog_service.update_image(
            admin, product.id, second.id, CatalogChanges({"alt_text": "Comida"})
        )
        assert catalog_repository.images[second.id].is_primary
        await catalog_service.update_presentation(
            admin, product.id, familiar.id, CatalogChanges({"is_default": True})
        )
        assert not catalog_repository.presentations[personal.id].is_default
        await catalog_service.update_presentation(
            admin, product.id, familiar.id, CatalogChanges({"name": "Grande"})
        )
        assert catalog_repository.presentations[familiar.id].is_default
        await catalog_service.archive_image(admin, product.id, second.id)
        await catalog_service.archive_presentation(admin, product.id, familiar.id)
        detail = await catalog_service.product_detail(branch_a, product.id)
        assert all(i.id != second.id for i in detail.images)
        assert all(p.id != familiar.id for p in detail.presentations)

    asyncio.run(scenario())


def test_reactivating_default_presentation_clears_previous_active_default(
    catalog_service, admin, catalog_repository
):
    async def scenario() -> None:
        _, product, personal, familiar, *_ = await seed(catalog_service, admin)
        await catalog_service.update_presentation(
            admin, product.id, personal.id, CatalogChanges({"is_active": False})
        )
        await catalog_service.update_presentation(
            admin, product.id, familiar.id, CatalogChanges({"is_default": True})
        )
        await catalog_service.update_presentation(
            admin, product.id, personal.id, CatalogChanges({"is_active": True})
        )
        assert catalog_repository.presentations[personal.id].is_default
        assert not catalog_repository.presentations[familiar.id].is_default

    asyncio.run(scenario())


def test_category_archive_conflicts_without_implicit_cascade(
    catalog_service, admin, catalog_repository
):
    async def scenario() -> None:
        category, product, *_ = await seed(catalog_service, admin)
        before_logs = len(catalog_repository.events)
        with pytest.raises(CatalogConflictError) as error:
            await catalog_service.archive_category(admin, category.id)
        assert error.value.code == "CATEGORY_HAS_ACTIVE_PRODUCTS"
        assert len(catalog_repository.events) == before_logs
        assert catalog_repository.categories[category.id].deleted_at is None
        await catalog_service.archive_product(admin, product.id)
        await catalog_service.archive_category(admin, category.id)
        assert catalog_repository.categories[category.id].deleted_at is not None
        assert product.id in catalog_repository.products

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "duplicate", ["category-slug", "category-name", "product-slug"]
)
def test_duplicate_logical_identity_uses_safe_conflict(
    catalog_service, admin, duplicate
):
    async def scenario() -> None:
        category, *_ = await seed(catalog_service, admin)
        with pytest.raises(CatalogConflictError):
            if duplicate == "category-slug":
                await catalog_service.create_category(
                    admin, CategoryCreate(name="Otro", slug="arroces")
                )
            elif duplicate == "category-name":
                await catalog_service.create_category(
                    admin, CategoryCreate(name="ARROCES", slug="otro")
                )
            else:
                await catalog_service.create_product(
                    admin,
                    ProductCreate(
                        category_id=category.id,
                        name="Otro",
                        slug="aeropuerto",
                        base_price=D("0"),
                    ),
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("resource", ["image", "presentation", "addon", "option"])
def test_children_cannot_be_changed_through_another_parent(
    catalog_service, admin, resource
):
    async def scenario() -> None:
        _, product, personal, _, addon, free, _ = await seed(catalog_service, admin)
        image = await catalog_service.create_image(
            admin, product.id, ImageCreate(url="https://example.test/a.png")
        )
        other = await catalog_service.create_product(
            admin,
            ProductCreate(
                category_id=product.category_id,
                name="Otro",
                slug="otro",
                base_price=D("1"),
            ),
        )
        with pytest.raises(CatalogNotFoundError):
            if resource == "option":
                await catalog_service.update_option(
                    admin,
                    other.id,
                    addon.id,
                    free.id,
                    CatalogChanges({"name": "Changed"}),
                )
            else:
                entity_id = {
                    "image": image.id,
                    "presentation": personal.id,
                    "addon": addon.id,
                }[resource]
                await getattr(catalog_service, f"update_{resource}")(
                    admin, other.id, entity_id, CatalogChanges({"sort_order": 1})
                )

    asyncio.run(scenario())


def test_branch_upsert_idempotent_price_reset_and_audit(
    catalog_service, admin, branch_a, catalog_repository
):
    async def scenario() -> None:
        _, product, *_ = await seed(catalog_service, admin)
        assert (
            await catalog_service.get_branch_product(admin, branch_a, product.id)
        ).price_override is None
        first = await catalog_service.upsert_branch_product(
            admin, branch_a, product.id, BranchProductConfig(False, D("25"))
        )
        second = await catalog_service.upsert_branch_product(
            admin, branch_a, product.id, BranchProductConfig(True, None)
        )
        assert first.id == second.id and len(catalog_repository.branch_products) == 1
        assert (
            await catalog_service.product_detail(branch_a, product.id)
        ).effective_base_price == D("20.00")
        audit = catalog_repository.events[-1]
        assert audit.action == "BRANCH_PRODUCT_UPDATED" and audit.branch_id == branch_a
        assert audit.before_state["price_override"] == "25"
        assert audit.after_state["price_override"] is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind",
    [
        "guest",
        "customer",
        "staff",
        "ended",
        "inactive-assignment",
        "inactive-user",
        "inactive-branch",
    ],
)
def test_current_authority_rejects_unauthorized_principals(
    catalog_service, admin, authorization, catalog_repository, branch_a, kind
):
    principal = admin
    if kind == "guest":
        principal = Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4())
    elif kind == "customer":
        principal = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    elif kind == "staff":
        authorization.grants[admin.user_id][0].role = "KITCHEN"
        authorization.grants[admin.user_id][0].permissions = ()
    elif kind == "ended":
        authorization.grants[admin.user_id][0].ended = True
    elif kind == "inactive-assignment":
        authorization.grants[admin.user_id][0].active = False
    elif kind == "inactive-user":
        authorization.inactive_users.add(admin.user_id)
    else:
        catalog_repository.branches.remove(branch_a)
    with pytest.raises(CatalogPermissionDeniedError):
        asyncio.run(catalog_service.list_categories(principal))


def test_global_admin_but_not_cross_branch_changes(
    catalog_service, admin, branch_a, branch_b
):
    async def scenario() -> None:
        _, product, *_ = await seed(catalog_service, admin)
        await catalog_service.update_product(
            admin, product.id, CatalogChanges({"base_price": D("21")})
        )
        with pytest.raises(CatalogPermissionDeniedError):
            await catalog_service.upsert_branch_product(
                admin, branch_b, product.id, BranchProductConfig(False, None)
            )
        assert (
            await catalog_service.product_detail(branch_a, product.id)
        ).effective_base_price == D("21.00")

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["commit", "audit"])
def test_failed_mutation_leaves_neither_entity_nor_orphan_audit(
    catalog_service, admin, catalog_repository, audit, failure
):
    initial_logs = len(catalog_repository.events)
    if failure == "commit":
        catalog_repository.fail_commit = True
    else:
        audit.fail_record = True
    with pytest.raises(RuntimeError):
        asyncio.run(
            catalog_service.create_category(
                admin, CategoryCreate(name="Fallido", slug="fallido")
            )
        )
    assert catalog_repository.categories == {}
    assert len(catalog_repository.events) == initial_logs
    assert catalog_repository.rollbacks == 1


def test_update_and_archive_audit_snapshots_are_json_safe(
    catalog_service, admin, catalog_repository
):
    async def scenario() -> None:
        _, product, *_ = await seed(catalog_service, admin)
        await catalog_service.update_product(
            admin, product.id, CatalogChanges({"base_price": D("24.50")})
        )
        event = catalog_repository.events[-1]
        assert event.action == "PRODUCT_UPDATED"
        assert event.before_state["base_price"] == "20.00"
        assert event.after_state["base_price"] == "24.50"
        await catalog_service.archive_product(admin, product.id)
        assert catalog_repository.events[-1].action == "PRODUCT_ARCHIVED"
        assert catalog_repository.events[-1].after_state["deleted_at"] is not None

    asyncio.run(scenario())


def test_future_selection_validates_prices_relations_and_notes(
    catalog_service, admin, branch_a
):
    async def scenario() -> None:
        _, product, personal, familiar, addon, free, paid = await seed(
            catalog_service, admin
        )
        selection = await catalog_service.validate_selection(
            branch_a,
            product.id,
            familiar.id,
            (AddonSelection(addon.id, (free.id, paid.id)),),
            notes="Sin cebolla",
        )
        assert selection.unit_price == D("38.50") and selection.addons_price == D(
            "3.50"
        )
        with pytest.raises(InvalidSelectionError):
            await catalog_service.validate_selection(branch_a, product.id, uuid4())
        with pytest.raises(InvalidSelectionError):
            await catalog_service.validate_selection(
                branch_a,
                product.id,
                personal.id,
                (AddonSelection(addon.id, (paid.id, paid.id)),),
            )
        await catalog_service.update_product(
            admin, product.id, CatalogChanges({"allows_notes": False})
        )
        with pytest.raises(InvalidSelectionError):
            await catalog_service.validate_selection(
                branch_a, product.id, personal.id, notes="Sin cebolla"
            )
        await catalog_service.upsert_branch_product(
            admin, branch_a, product.id, BranchProductConfig(False, None)
        )
        with pytest.raises(ProductNotAvailableError):
            await catalog_service.validate_selection(branch_a, product.id, personal.id)

    asyncio.run(scenario())


def test_required_addon_min_max_and_foreign_option(catalog_service, admin, branch_a):
    async def scenario() -> None:
        _, product, personal, _, addon, free, _ = await seed(catalog_service, admin)
        await catalog_service.update_addon(
            admin,
            product.id,
            addon.id,
            CatalogChanges({"is_required": True, "max_select": 1}),
        )
        for choices in (
            (),
            (AddonSelection(addon.id, (uuid4(),)),),
            (AddonSelection(uuid4(), (free.id,)),),
        ):
            with pytest.raises(InvalidSelectionError):
                await catalog_service.validate_selection(
                    branch_a, product.id, personal.id, choices
                )
        with pytest.raises(InvalidCatalogDataError):
            await catalog_service.update_addon(
                admin, product.id, addon.id, CatalogChanges({"min_select": 2})
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("where", ["branch", "category", "product"])
def test_missing_relations(catalog_service, admin, branch_a, where):
    async def scenario() -> None:
        with pytest.raises(CatalogNotFoundError):
            if where == "branch":
                await catalog_service.menu(uuid4())
            elif where == "category":
                await catalog_service.create_product(
                    admin,
                    ProductCreate(
                        category_id=uuid4(), name="P", slug="p", base_price=D("1")
                    ),
                )
            else:
                await catalog_service.product_detail(branch_a, uuid4())

    asyncio.run(scenario())


def test_application_also_rejects_mass_assignment(catalog_service, admin):
    async def scenario() -> None:
        category, *_ = await seed(catalog_service, admin)
        with pytest.raises(InvalidCatalogDataError):
            await catalog_service.update_category(
                admin, category.id, CatalogChanges({"deleted_at": utc_now()})
            )

    asyncio.run(scenario())
