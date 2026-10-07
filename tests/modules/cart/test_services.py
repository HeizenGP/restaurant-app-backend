import asyncio
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cart.application.dtos import AddonSelection, ItemCreate, ItemUpdate
from app.modules.cart.application.errors import (
    ActiveCartExistsError,
    CartBranchInvalidError,
    CartItemNotFoundError,
    CartNotFoundError,
    CartProductUnavailableError,
    CartRecalculationFailedError,
    CartSelectionInvalidError,
    InvalidCartDataError,
)
from app.modules.cart.domain.models import CartStatus
from app.modules.catalog.application.dtos import (
    BranchProductConfig,
    CatalogChanges,
    PresentationCreate,
    ProductCreate,
)
from app.shared.application.exceptions import (
    DependencyUnavailableError,
    UnauthorizedError,
)
from tests.modules.cart.fakes import CartSetup


def command(setup: CartSetup, **values) -> ItemCreate:
    return ItemCreate(
        product_id=setup.product.id,
        presentation_id=setup.personal.id,
        quantity=2,
        **values,
    )


async def start(setup: CartSetup, **values):
    await setup.service.create_cart(setup.guest, setup.branch)
    return await setup.service.add_item(setup.guest, command(setup, **values))


@pytest.mark.parametrize("who", ["guest", "registered"])
def test_customer_creates_only_one_active_cart_and_can_abandon(setup: CartSetup, who):
    async def scenario():
        principal = getattr(setup, who)
        cart = await setup.service.create_cart(principal, setup.branch)
        assert cart.status == CartStatus.ACTIVE and cart.items == ()
        assert cart.total == Decimal("0.00")
        with pytest.raises(ActiveCartExistsError):
            await setup.service.create_cart(principal, setup.other_branch)
        assert len(setup.repository.carts) == 1
        await setup.service.abandon_cart(principal)
        with pytest.raises(CartNotFoundError):
            await setup.service.get_cart(principal)
        with pytest.raises(CartNotFoundError):
            await setup.service.add_item(principal, command(setup))
        new = await setup.service.create_cart(principal, setup.other_branch)
        assert new.id != cart.id and new.branch_id == setup.other_branch
        assert setup.repository.carts[cart.id].status == CartStatus.ABANDONED

    asyncio.run(scenario())


@pytest.mark.parametrize("inactive", [False, True])
def test_cart_rejects_missing_or_inactive_branch(setup: CartSetup, inactive):
    branch = setup.branch if inactive else uuid4()
    if inactive:
        setup.catalog_repository.branches.remove(branch)
    with pytest.raises(CartBranchInvalidError):
        asyncio.run(setup.service.create_cart(setup.guest, branch))
    assert not setup.repository.carts


def test_two_customers_have_independent_carts_and_ownership(setup: CartSetup):
    async def scenario():
        own = await start(setup)
        await setup.service.create_cart(setup.registered, setup.branch)
        foreign = await setup.service.add_item(setup.registered, command(setup))
        for operation in (
            setup.service.update_item(
                setup.guest,
                foreign.id,
                ItemUpdate(provided_fields=frozenset({"quantity"}), quantity=5),
            ),
            setup.service.delete_item(setup.guest, foreign.id),
        ):
            with pytest.raises(CartItemNotFoundError):
                await operation
        await setup.service.abandon_cart(setup.guest)
        assert (await setup.service.get_cart(setup.registered)).items[
            0
        ].id == foreign.id
        assert own.id in setup.repository.items

    asyncio.run(scenario())


def test_customer_identity_required_without_cart_permission(setup: CartSetup):
    staff = Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())
    with pytest.raises(UnauthorizedError):
        asyncio.run(setup.service.create_cart(staff, setup.branch))


def test_snapshots_come_from_catalog_with_free_paid_options_and_override(
    setup: CartSetup,
):
    async def scenario():
        await setup.catalog.upsert_branch_product(
            setup.admin,
            setup.branch,
            setup.product.id,
            BranchProductConfig(True, Decimal("22.00")),
        )
        item = await start(
            setup,
            addons=(AddonSelection(setup.addon.id, (setup.free.id, setup.paid.id)),),
            notes=" Sin cebolla ",
        )
        assert (
            item.base_price_snapshot
            == item.presentation_price_snapshot
            == Decimal("22.00")
        )
        assert item.addons_price_snapshot == Decimal("3.50")
        assert item.unit_price_snapshot == Decimal("25.50")
        assert item.line_total == Decimal("51.00") and item.notes == "Sin cebolla"
        assert sorted(
            option.additional_price_snapshot for option in item.selected_options
        ) == [Decimal("0.00"), Decimal("3.50")]
        view = await setup.service.get_cart(setup.guest)
        assert view.subtotal == view.total == Decimal("51.00") and view.item_count == 2
        assert view.charges_total == view.discount_total == Decimal("0.00")

    asyncio.run(scenario())


def test_duplicate_posts_are_independent_lines_and_units_not_line_count(
    setup: CartSetup,
):
    async def scenario():
        first = await start(setup)
        second = await setup.service.add_item(setup.guest, command(setup))
        assert first.id != second.id
        view = await setup.service.get_cart(setup.guest)
        assert len(view.items) == 2 and view.item_count == 4
        assert view.total == Decimal("80.00")

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalid",
    [
        "sold-out",
        "inactive",
        "archived",
        "category-inactive",
        "category-archived",
        "presentation-inactive",
        "presentation-archived",
        "branch-inactive",
        "wrong-presentation",
        "wrong-product",
        "wrong-addon",
        "wrong-option",
        "option-inactive",
        "option-archived",
        "addon-inactive",
        "addon-archived",
        "duplicate-option",
        "duplicate-group",
        "notes",
        "required",
        "minimum",
        "maximum",
    ],
)
def test_catalog_rejects_invalid_selections_and_cart_stays_unchanged(
    setup: CartSetup, invalid
):
    async def scenario():
        await setup.service.create_cart(setup.guest, setup.branch)
        values = {}
        if invalid == "sold-out":
            await setup.catalog.upsert_branch_product(
                setup.admin,
                setup.branch,
                setup.product.id,
                BranchProductConfig(False, None),
            )
        elif invalid in {
            "inactive",
            "archived",
            "category-inactive",
            "category-archived",
            "notes",
        }:
            if invalid == "inactive":
                await setup.catalog.update_product(
                    setup.admin, setup.product.id, CatalogChanges({"is_active": False})
                )
            elif invalid == "archived":
                await setup.catalog.archive_product(setup.admin, setup.product.id)
            elif invalid.startswith("category"):
                changes = {"is_active": False}
                await setup.catalog.update_category(
                    setup.admin, setup.category.id, CatalogChanges(changes)
                )
                if invalid == "category-archived":
                    await setup.catalog.update_product(
                        setup.admin,
                        setup.product.id,
                        CatalogChanges({"is_active": False}),
                    )
                    await setup.catalog.archive_category(setup.admin, setup.category.id)
            else:
                await setup.catalog.update_product(
                    setup.admin,
                    setup.product.id,
                    CatalogChanges({"allows_notes": False}),
                )
                values["notes"] = "Sin cebolla"
        elif invalid.startswith("presentation"):
            if invalid.endswith("inactive"):
                await setup.catalog.update_presentation(
                    setup.admin,
                    setup.product.id,
                    setup.personal.id,
                    CatalogChanges({"is_active": False}),
                )
            else:
                await setup.catalog.archive_presentation(
                    setup.admin, setup.product.id, setup.personal.id
                )
        elif invalid == "branch-inactive":
            setup.catalog_repository.branches.remove(setup.branch)
        elif invalid.startswith("wrong"):
            if invalid == "wrong-product":
                values["product_id"] = uuid4()
            elif invalid == "wrong-presentation":
                other = await setup.catalog.create_product(
                    setup.admin,
                    ProductCreate(
                        category_id=setup.category.id,
                        name="Otro",
                        slug="otro",
                        base_price=Decimal("1"),
                    ),
                )
                presentation = await setup.catalog.create_presentation(
                    setup.admin,
                    other.id,
                    PresentationCreate(name="Otra", price_delta=Decimal("0")),
                )
                values["presentation_id"] = presentation.id
            else:
                values["addons"] = (
                    AddonSelection(
                        uuid4() if invalid == "wrong-addon" else setup.addon.id,
                        (uuid4(),),
                    ),
                )
        else:
            options = (setup.paid.id,)
            if invalid.startswith("option"):
                if invalid.endswith("inactive"):
                    await setup.catalog.update_option(
                        setup.admin,
                        setup.product.id,
                        setup.addon.id,
                        setup.paid.id,
                        CatalogChanges({"is_active": False}),
                    )
                else:
                    await setup.catalog.archive_option(
                        setup.admin, setup.product.id, setup.addon.id, setup.paid.id
                    )
            elif invalid.startswith("addon"):
                if invalid.endswith("inactive"):
                    await setup.catalog.update_addon(
                        setup.admin,
                        setup.product.id,
                        setup.addon.id,
                        CatalogChanges({"is_active": False}),
                    )
                else:
                    await setup.catalog.archive_addon(
                        setup.admin, setup.product.id, setup.addon.id
                    )
            elif invalid == "duplicate-option":
                options = (setup.paid.id, setup.paid.id)
            elif invalid == "required":
                await setup.catalog.update_addon(
                    setup.admin,
                    setup.product.id,
                    setup.addon.id,
                    CatalogChanges({"is_required": True}),
                )
                options = ()
            elif invalid == "minimum":
                await setup.catalog.update_addon(
                    setup.admin,
                    setup.product.id,
                    setup.addon.id,
                    CatalogChanges({"min_select": 2}),
                )
            elif invalid == "maximum":
                await setup.catalog.update_addon(
                    setup.admin,
                    setup.product.id,
                    setup.addon.id,
                    CatalogChanges({"max_select": 1}),
                )
                options = (setup.free.id, setup.paid.id)
            groups = (AddonSelection(setup.addon.id, options),)
            values["addons"] = groups * 2 if invalid == "duplicate-group" else groups
        current = replace(command(setup), **values)
        with pytest.raises((CartSelectionInvalidError, CartProductUnavailableError)):
            await setup.service.add_item(setup.guest, current)
        assert not setup.repository.items and setup.repository.rollbacks == 1

    asyncio.run(scenario())


def test_rf16_always_uses_cart_branch_not_other_available_branch(setup: CartSetup):
    async def scenario():
        await setup.catalog.upsert_branch_product(
            setup.admin,
            setup.branch,
            setup.product.id,
            BranchProductConfig(False, Decimal("25")),
        )
        assert (
            await setup.catalog.product_detail(setup.other_branch, setup.product.id)
        ).is_available
        await setup.service.create_cart(setup.guest, setup.branch)
        with pytest.raises(CartProductUnavailableError):
            await setup.service.add_item(setup.guest, command(setup))

    asyncio.run(scenario())


def test_patch_omission_null_presentation_and_addon_replacement(setup: CartSetup):
    async def scenario():
        item = await start(
            setup,
            notes="Sin cebolla",
            addons=(AddonSelection(setup.addon.id, (setup.paid.id,)),),
        )
        updated = await setup.service.update_item(
            setup.guest,
            item.id,
            ItemUpdate(provided_fields=frozenset({"quantity"}), quantity=3),
        )
        assert (
            updated.notes == "Sin cebolla"
            and updated.selected_options == item.selected_options
        )
        changed = await setup.service.update_item(
            setup.guest,
            item.id,
            ItemUpdate(
                provided_fields=frozenset({"notes", "presentation_id", "addons"}),
                notes=None,
                presentation_id=setup.family.id,
                addons=(),
            ),
        )
        assert changed.notes is None and not changed.selected_options
        assert changed.presentation_price_snapshot == Decimal(
            "35.00"
        ) and changed.line_total == Decimal("105.00")
        assert changed.product_id == item.product_id

    asyncio.run(scenario())


def test_quantity_patch_revalidates_and_never_deletes(setup: CartSetup):
    async def scenario():
        item = await start(setup)
        with pytest.raises(InvalidCartDataError):
            await setup.service.update_item(
                setup.guest,
                item.id,
                ItemUpdate(provided_fields=frozenset({"quantity"}), quantity=0),
            )
        await setup.catalog.upsert_branch_product(
            setup.admin,
            setup.branch,
            setup.product.id,
            BranchProductConfig(False, None),
        )
        with pytest.raises(CartProductUnavailableError):
            await setup.service.update_item(
                setup.guest,
                item.id,
                ItemUpdate(provided_fields=frozenset({"quantity"}), quantity=1),
            )
        assert setup.repository.items[item.id] == item
        await setup.service.delete_item(setup.guest, item.id)
        assert not setup.repository.items

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "fields",
    [
        frozenset(),
        frozenset({"customer_id"}),
        frozenset({"quantity"}),
        frozenset({"addons"}),
        frozenset({"presentation_id"}),
    ],
)
def test_application_rejects_unsafe_or_null_patch(setup: CartSetup, fields):
    async def scenario():
        item = await start(setup)
        with pytest.raises(InvalidCartDataError):
            await setup.service.update_item(
                setup.guest, item.id, ItemUpdate(provided_fields=fields)
            )

    asyncio.run(scenario())


def test_get_is_read_only_and_recalculate_updates_all_snapshots(setup: CartSetup):
    async def scenario():
        item = await start(
            setup, addons=(AddonSelection(setup.addon.id, (setup.paid.id,)),)
        )
        commits = setup.repository.commits
        await setup.catalog.update_product(
            setup.admin,
            setup.product.id,
            CatalogChanges({"base_price": Decimal("22.00")}),
        )
        await setup.catalog.update_presentation(
            setup.admin,
            setup.product.id,
            setup.personal.id,
            CatalogChanges({"price_delta": Decimal("1.00")}),
        )
        await setup.catalog.update_option(
            setup.admin,
            setup.product.id,
            setup.addon.id,
            setup.paid.id,
            CatalogChanges({"additional_price": Decimal("5.00")}),
        )
        view = await setup.service.get_cart(setup.guest)
        assert view.items[0].unit_price_snapshot == Decimal("23.50")
        assert setup.repository.commits == commits
        view = await setup.service.recalculate_cart(setup.guest)
        updated = view.items[0]
        assert updated.base_price_snapshot == Decimal("22.00")
        assert updated.presentation_price_snapshot == Decimal("23.00")
        assert updated.addons_price_snapshot == Decimal("5.00")
        assert updated.selected_options[0].additional_price_snapshot == Decimal("5.00")
        assert updated.unit_price_snapshot == Decimal(
            "28.00"
        ) and view.total == Decimal("56.00")
        assert updated.selected_options[0].id == item.selected_options[0].id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "invalid", ["sold-out", "presentation", "addon", "option", "notes", "branch"]
)
def test_recalculation_invalid_line_keeps_every_snapshot_and_item(
    setup: CartSetup, invalid
):
    async def scenario():
        a = await start(setup)
        b = await setup.service.add_item(
            setup.guest,
            command(
                setup,
                addons=(AddonSelection(setup.addon.id, (setup.paid.id,)),),
                notes="Sin cebolla",
            ),
        )
        c = await setup.service.add_item(setup.guest, command(setup))
        before = dict(setup.repository.items)
        await setup.catalog.update_product(
            setup.admin, setup.product.id, CatalogChanges({"base_price": Decimal("25")})
        )
        if invalid == "sold-out":
            await setup.catalog.upsert_branch_product(
                setup.admin,
                setup.branch,
                setup.product.id,
                BranchProductConfig(False, None),
            )
        elif invalid == "presentation":
            await setup.catalog.update_presentation(
                setup.admin,
                setup.product.id,
                setup.personal.id,
                CatalogChanges({"is_active": False}),
            )
        elif invalid == "addon":
            await setup.catalog.archive_addon(
                setup.admin, setup.product.id, setup.addon.id
            )
        elif invalid == "option":
            await setup.catalog.archive_option(
                setup.admin, setup.product.id, setup.addon.id, setup.paid.id
            )
        elif invalid == "notes":
            await setup.catalog.update_product(
                setup.admin, setup.product.id, CatalogChanges({"allows_notes": False})
            )
        else:
            setup.catalog_repository.branches.remove(setup.branch)
        with pytest.raises(CartRecalculationFailedError):
            await setup.service.recalculate_cart(setup.guest)
        assert setup.repository.items == before
        assert {a.id, b.id, c.id} == set(setup.repository.items)
        assert setup.repository.updates == 0
        assert len((await setup.service.get_cart(setup.guest)).items) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["commit", "second-update"])
def test_recalculate_database_failure_rolls_back_written_lines(
    setup: CartSetup, failure
):
    async def scenario():
        await start(setup)
        await setup.service.add_item(setup.guest, command(setup))
        before = dict(setup.repository.items)
        await setup.catalog.update_product(
            setup.admin, setup.product.id, CatalogChanges({"base_price": Decimal("29")})
        )
        if failure == "commit":
            setup.repository.fail_commit = True
        else:
            setup.repository.fail_update_at = 2
        with pytest.raises(RuntimeError):
            await setup.service.recalculate_cart(setup.guest)
        assert setup.repository.items == before

    asyncio.run(scenario())


def test_catalog_dependency_failure_is_not_hidden_as_business_error(setup: CartSetup):
    async def scenario():
        await start(setup)
        setup.service._catalog.validate_selection = AsyncMock(
            side_effect=DependencyUnavailableError("Database unavailable")
        )
        with pytest.raises(DependencyUnavailableError):
            await setup.service.recalculate_cart(setup.guest)

    asyncio.run(scenario())


def test_cart_mutations_do_not_add_administrative_audit_events_and_lock_parent_first(
    setup: CartSetup,
):
    async def scenario():
        count = len(setup.catalog_repository.events)
        item = await start(setup)
        setup.repository.calls.clear()
        await setup.service.update_item(
            setup.guest,
            item.id,
            ItemUpdate(provided_fields=frozenset({"notes"}), notes="Sin ají"),
        )
        assert setup.repository.calls[:2] == [("cart", True), ("item", True)]
        await setup.service.recalculate_cart(setup.guest)
        await setup.service.delete_item(setup.guest, item.id)
        await setup.service.abandon_cart(setup.guest)
        assert len(setup.catalog_repository.events) == count

    asyncio.run(scenario())


def test_customer_id_preserves_cart_when_principal_becomes_registered(setup: CartSetup):
    async def scenario():
        await start(setup)
        principal = Principal(
            principal_type=PrincipalType.REGISTERED,
            user_id=uuid4(),
            customer_id=setup.guest.customer_id,
        )
        assert (await setup.service.get_cart(principal)).items

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "operation", ["add", "patch", "delete", "recalculate", "abandon"]
)
def test_every_cart_mutation_serializes_on_the_same_parent(setup: CartSetup, operation):
    async def scenario():
        item = await start(setup)
        setup.repository.calls.clear()
        if operation == "add":
            await setup.service.add_item(setup.guest, command(setup))
        elif operation == "patch":
            await setup.service.update_item(
                setup.guest,
                item.id,
                ItemUpdate(provided_fields=frozenset({"quantity"}), quantity=3),
            )
        elif operation == "delete":
            await setup.service.delete_item(setup.guest, item.id)
        elif operation == "recalculate":
            await setup.service.recalculate_cart(setup.guest)
        else:
            await setup.service.abandon_cart(setup.guest)
        assert setup.repository.calls[0] == ("cart", True)

    asyncio.run(scenario())


def test_simultaneous_create_has_one_winner_and_safe_conflict(setup: CartSetup):
    async def scenario():
        # Force both application prechecks to observe no ACTIVE cart.
        repository = setup.repository
        original_find = repository.find_active
        arrived = 0
        both_ready = asyncio.Event()

        async def racing_find(customer_id, *, lock=False):
            nonlocal arrived
            found = await original_find(customer_id, lock=lock)
            if arrived < 2:
                arrived += 1
                if arrived == 2:
                    both_ready.set()
                await both_ready.wait()
            return found

        repository.find_active = racing_find
        outcomes = await asyncio.gather(
            setup.service.create_cart(setup.guest, setup.branch),
            setup.service.create_cart(setup.guest, setup.branch),
            return_exceptions=True,
        )
        assert (
            sum(isinstance(result, ActiveCartExistsError) for result in outcomes) == 1
        )
        assert len(repository.carts) == 1

    asyncio.run(scenario())
