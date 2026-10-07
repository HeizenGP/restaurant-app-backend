import asyncio
from dataclasses import replace
from datetime import time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.cart.application.dtos import ItemCreate, ItemUpdate
from app.modules.cart.application.errors import CartNotFoundError
from app.modules.cart.domain.models import CartStatus
from app.modules.catalog.application.dtos import BranchProductConfig
from app.modules.orders.application.dtos import OrderCreate, PreparationEstimate
from app.modules.orders.application.errors import (
    InvalidOrderDataError,
    OrderConflictError,
    OrderNotFoundError,
    OrderPermissionDeniedError,
    OrderResourceNotFoundError,
    OrderUniqueConflictError,
)
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    DeliveryZone,
    OrderMode,
    OrderStatus,
    PaymentStatus,
)


def run(awaitable):
    return asyncio.run(awaitable)


def create(setup, key="first", command=None, principal=None):
    return run(
        setup.service.create(
            principal or setup.cart.guest, key, command or setup.local()
        )
    )


@pytest.mark.parametrize("who", ["guest", "registered"])
def test_customer_converts_cart_to_historical_order(setup, who):
    principal = getattr(setup.cart, who)
    if who == "registered":
        run(setup.prepare(principal))
    order = create(setup, principal=principal)
    assert order.customer_id == principal.customer_id
    assert order.branch_id == setup.cart.branch
    assert (
        setup.store.cart.repository.carts[order.source_cart_id].status
        == CartStatus.CHECKED_OUT
    )
    assert (
        order.history[0].from_status is None
        and order.history[0].to_status == order.status
    )
    assert order.payment_status == PaymentStatus.PENDING
    assert setup.store.commits == 1
    assert ("lock_cart", True) in setup.session.calls


def test_checked_out_cart_cannot_be_modified_or_recalculated(setup):
    order = create(setup)
    for operation in (
        setup.cart.service.recalculate_cart(setup.cart.guest),
        setup.cart.service.abandon_cart(setup.cart.guest),
        setup.cart.service.update_item(
            setup.cart.guest,
            order.items[0].id,
            ItemUpdate(provided_fields=frozenset({"quantity"}), quantity=2),
        ),
    ):
        with pytest.raises(CartNotFoundError):
            run(operation)
    assert (
        setup.cart.repository.carts[order.source_cart_id].status
        == CartStatus.CHECKED_OUT
    )
    assert len(setup.store.orders) == 1


def test_empty_cart_rollback(setup):
    setup.cart.repository.items.clear()
    with pytest.raises(OrderConflictError, match="conflicts") as caught:
        create(setup)
    assert caught.value.code == "EMPTY_CART"
    assert not setup.store.orders
    assert all(
        cart.status == CartStatus.ACTIVE
        for cart in setup.cart.repository.carts.values()
    )


@pytest.mark.parametrize("fail", ["fail_commit", "fail_checkout", "fail_item"])
def test_failure_after_insert_rolls_back_all_order_components_and_cart(setup, fail):
    if fail == "fail_item":
        run(
            setup.cart.service.add_item(
                setup.cart.guest,
                ItemCreate(
                    product_id=setup.cart.product.id,
                    presentation_id=setup.cart.personal.id,
                    quantity=2,
                    notes=None,
                ),
            )
        )
        setup.session.fail_item = 2
    else:
        setattr(setup.session, fail, True)
    with pytest.raises(RuntimeError):
        create(setup)
    assert not setup.store.orders
    assert setup.store.commits == 0 and setup.store.rollbacks == 1
    assert all(
        cart.status == CartStatus.ACTIVE
        for cart in setup.cart.repository.carts.values()
    )
    if fail == "fail_item":
        assert setup.session.calls[-2:] == [("insert_item", 1), ("insert_item", 2)]


@pytest.mark.parametrize(
    "mutation", ["product", "presentation", "notes", "availability", "branch"]
)
def test_final_catalog_revalidation_is_required(setup, mutation):
    repo = setup.cart.catalog_repository
    if mutation == "product":
        repo.products[setup.cart.product.id] = replace(
            setup.cart.product, is_active=False
        )
    elif mutation == "presentation":
        repo.presentations[setup.cart.personal.id] = replace(
            setup.cart.personal, is_active=False
        )
    elif mutation == "notes":
        old = next(iter(setup.cart.repository.items.values()))
        setup.cart.repository.items[old.id] = replace(old, notes="No onions")
        repo.products[setup.cart.product.id] = replace(
            setup.cart.product, allows_notes=False
        )
    elif mutation == "availability":
        run(
            setup.cart.catalog.upsert_branch_product(
                setup.cart.admin,
                setup.cart.branch,
                setup.cart.product.id,
                BranchProductConfig(is_available=False, price_override=None),
            )
        )
    else:
        repo.branches.remove(setup.cart.branch)
    with pytest.raises(OrderConflictError) as caught:
        create(setup)
    assert caught.value.code == "ORDER_SELECTION_INVALID"
    assert not setup.store.orders
    assert next(iter(setup.cart.repository.carts.values())).status == CartStatus.ACTIVE


def test_checkout_uses_current_price_not_old_cart_snapshot(setup):
    setup.cart.catalog_repository.products[setup.cart.product.id] = replace(
        setup.cart.product, base_price=Decimal("30.00")
    )
    order = create(setup)
    assert order.subtotal == Decimal("30.00")
    assert next(
        iter(setup.cart.repository.items.values())
    ).base_price_snapshot == Decimal("20.00")
    assert order.items[0].base_price_snapshot == Decimal("30.00")


def test_all_names_contact_and_address_are_immutable_snapshots(setup):
    run(setup.cart.service.abandon_cart(setup.cart.guest))
    run(setup.prepare(addons=True))
    order = create(setup, command=setup.delivery())
    repo = setup.cart.catalog_repository
    for mapping, old in (
        (repo.products, setup.cart.product),
        (repo.presentations, setup.cart.personal),
        (repo.addons, setup.cart.addon),
        (repo.options, setup.cart.paid),
    ):
        mapping[old.id] = replace(old, name="Changed later")
    setup.store.customers[order.customer_id] = replace(
        setup.store.customers[order.customer_id],
        full_name="Changed contact",
        phone="+51900000999",
    )
    setup.store.addresses[setup.address.id] = (
        order.customer_id,
        replace(
            setup.address, address_line="New address", recipient_name="New recipient"
        ),
    )
    historical = run(setup.service.get(setup.cart.guest, order.id))
    assert historical.items[0].product_name_snapshot == setup.cart.product.name
    assert historical.items[0].presentation_name_snapshot == setup.cart.personal.name
    assert (
        historical.items[0].addon_options[0].addon_name_snapshot
        == setup.cart.addon.name
    )
    assert (
        historical.items[0].addon_options[0].option_name_snapshot
        == setup.cart.paid.name
    )
    assert historical.customer_name_snapshot == "Customer original"
    assert historical.customer_phone_snapshot == "+51900000111"
    assert (
        historical.delivery_details.address_line_snapshot == setup.address.address_line
    )
    assert (
        historical.delivery_details.recipient_name_snapshot
        == setup.address.recipient_name
    )


def test_replay_same_key_same_request_and_payload_conflict(setup):
    first = create(setup)
    assert create(setup).id == first.id
    with pytest.raises(OrderConflictError) as caught:
        create(setup, command=setup.local("ONLINE"))
    assert caught.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert len(setup.store.orders) == 1 and setup.store.commits == 1


def test_replay_remains_original_even_after_new_active_cart(setup):
    first = create(setup)
    run(setup.prepare(quantity=2))
    assert create(setup).id == first.id
    second = create(setup, key="second")
    assert second.source_cart_id != first.source_cart_id
    assert second.order_number > first.order_number


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_requests_create_exactly_one_order(setup, same_key):
    async def verify():
        async def request(key):
            session, service = setup.fork()
            try:
                await asyncio.sleep(0)
                return await service.create(setup.cart.guest, key, setup.local())
            finally:
                session.close()

        results = await asyncio.gather(
            request("key-a"),
            request("key-a" if same_key else "key-b"),
            return_exceptions=True,
        )
        assert len(setup.store.orders) == 1 and setup.store.commits == 1
        if same_key:
            assert results[0].id == results[1].id
        else:
            assert sum(isinstance(value, OrderConflictError) for value in results) == 1

    run(verify())


def test_unique_constraint_race_is_resolved_by_existing_fingerprint(setup):
    winner = create(setup)
    setup.session.by_idempotency = AsyncMock(side_effect=[None, None, winner])
    setup.session.create = AsyncMock(
        side_effect=OrderUniqueConflictError("uq_orders_customer_idempotency")
    )
    run(setup.prepare())
    result = create(setup)
    assert result.id == winner.id
    assert setup.store.rollbacks == 1


@pytest.mark.parametrize("case", ["invalid", "inactive", "other_branch"])
def test_local_qr_validation(setup, case):
    command = setup.local()
    if case == "invalid":
        command = replace(command, table_qr_token=uuid4())
    elif case == "inactive":
        setup.store.tables[setup.table.id] = replace(setup.table, is_active=False)
    else:
        setup.store.tables[setup.table.id] = replace(
            setup.table, branch_id=setup.cart.other_branch
        )
    with pytest.raises((OrderResourceNotFoundError, OrderConflictError)) as caught:
        create(setup, command=command)
    assert caught.value.code == (
        "TABLE_BRANCH_MISMATCH" if case == "other_branch" else "TABLE_NOT_FOUND"
    )
    assert not setup.store.orders


@pytest.mark.parametrize(
    "method,confirm,status",
    [
        ("ONLINE", True, OrderStatus.PENDING_PAYMENT),
        ("CASH", True, OrderStatus.PENDING_CASH_CONFIRMATION),
        ("CASH", False, OrderStatus.WAITING),
    ],
)
def test_local_cash_configuration_and_online_gating(setup, method, confirm, status):
    setup.store.settings[setup.cart.branch] = BranchOrderSettings(
        branch_id=setup.cart.branch, cash_payment_requires_confirmation=confirm
    )
    order = create(setup, command=setup.local(method))
    assert order.status == status and order.payment_status == PaymentStatus.PENDING
    assert (order.confirmed_at is not None) == (status == OrderStatus.WAITING)


def test_same_table_supports_multiple_orders_and_label_snapshot(setup):
    first = create(setup)
    run(setup.prepare())
    second = create(setup, key="second")
    assert (
        first.local_details.restaurant_table_id
        == second.local_details.restaurant_table_id
    )
    run(
        setup.admin_service.update_table(
            setup.cart.admin,
            setup.cart.branch,
            setup.table.id,
            {"label": "Renamed table"},
        )
    )
    assert first.local_details.table_label_snapshot == "Mesa Test"


def test_cash_release_is_not_payment_and_history_is_transactional(setup):
    order = create(setup)
    released = run(setup.service.confirm_cash_release(setup.cart.admin, order.id))
    assert (
        released.status == OrderStatus.WAITING
        and released.payment_status == PaymentStatus.PENDING
    )
    assert len(released.history) == 2
    assert released.history[-1].from_status == OrderStatus.PENDING_CASH_CONFIRMATION
    assert released.history[-1].changed_by_user_id == setup.cart.admin.user_id
    assert released.confirmed_at == setup.now
    with pytest.raises(OrderConflictError):
        run(setup.service.confirm_cash_release(setup.cart.admin, order.id))


@pytest.mark.parametrize("who", ["guest", "registered", "foreign"])
def test_cash_release_is_branch_authorized(setup, who):
    order = create(setup)
    principal = (
        getattr(setup.cart, who)
        if who != "foreign"
        else replace(setup.cart.admin, user_id=uuid4())
    )
    with pytest.raises(OrderPermissionDeniedError):
        run(setup.service.confirm_cash_release(principal, order.id))
    assert setup.store.orders[order.id].status == OrderStatus.PENDING_CASH_CONFIRMATION


def test_cash_release_online_rejected(setup):
    order = create(setup, command=setup.local("ONLINE"))
    with pytest.raises(OrderConflictError) as caught:
        run(setup.service.confirm_cash_release(setup.cart.admin, order.id))
    assert caught.value.code == "CASH_RELEASE_NOT_ALLOWED"


def test_pickup_schedule_snapshots_and_timezone_canonical_replay(setup):
    command = OrderCreate(
        mode=OrderMode.PICKUP, requested_pickup_at=setup.now + timedelta(hours=2)
    )
    order = create(setup, command=command)
    details = order.pickup_details
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert (
        details.calculated_kitchen_release_at
        == command.requested_pickup_at - timedelta(minutes=25)
    )
    assert details.estimated_ready_at == command.requested_pickup_at - timedelta(
        minutes=5
    )
    assert details.pickup_name_snapshot == "Customer original"
    same_time = command.requested_pickup_at.astimezone(timezone(timedelta(hours=-5)))
    assert (
        create(setup, command=replace(command, requested_pickup_at=same_time)).id
        == order.id
    )


@pytest.mark.parametrize("case", ["past", "soon", "closed", "naive"])
def test_pickup_invalid_time_rolls_back(setup, case):
    requested = setup.now + timedelta(hours=2)
    if case == "past":
        requested = setup.now - timedelta(minutes=1)
    elif case == "soon":
        requested = setup.now + timedelta(minutes=24)
    elif case == "naive":
        requested = requested.replace(tzinfo=None)
    else:
        setup.store.hours[setup.cart.branch] = ((1, time(1), time(2), False),)
    with pytest.raises((OrderConflictError, InvalidOrderDataError)):
        create(
            setup,
            command=OrderCreate(mode=OrderMode.PICKUP, requested_pickup_at=requested),
        )
    assert not setup.store.orders


@pytest.mark.parametrize("status", list(OrderStatus))
def test_queue_only_counts_waiting_and_preparing(setup, status):
    setup.store.orders[uuid4()] = SimpleNamespace(
        branch_id=setup.cart.branch, status=status
    )
    settings = BranchOrderSettings(branch_id=setup.cart.branch)
    estimate = run(setup.session.estimate(setup.cart.branch, settings))
    count = 1 if status in {OrderStatus.WAITING, OrderStatus.PREPARING} else 0
    assert estimate.queue_depth == count and estimate.total_minutes == 20 + 5 * count


@pytest.mark.parametrize(
    "district",
    [
        "Tarapoto",
        "tarapoto",
        " TARAPOTO ",
        "Morales",
        "MORALES",
        "La Banda de Shilcayo",
    ],
)
def test_free_zone_policy_has_precedence_over_paid_branch_override(setup, district):
    setup.store.addresses[setup.address.id] = (
        setup.cart.guest.customer_id,
        replace(setup.address, district=district),
    )
    override = DeliveryZone(
        branch_id=setup.cart.branch,
        name="Paid override",
        district=district.strip(),
        delivery_fee=Decimal("8.00"),
    )
    setup.store.zones[override.id] = override
    order = create(setup, command=setup.delivery())
    assert order.delivery_fee == Decimal("0.00") and order.total == order.subtotal


def test_paid_delivery_fee_and_queue_travel_eta(setup):
    address = replace(setup.address, district="Juan Guerra")
    setup.store.addresses[address.id] = (setup.cart.guest.customer_id, address)
    zone = DeliveryZone(
        branch_id=setup.cart.branch,
        name="Paid zone",
        district="Juan Guerra",
        delivery_fee=Decimal("8.00"),
        estimated_travel_minutes=30,
    )
    setup.store.zones[zone.id] = zone
    setup.session.estimate = AsyncMock(return_value=PreparationEstimate(3, 20, 15))
    order = create(setup, command=setup.delivery())
    assert order.total == Decimal(
        "28.00"
    ) and order.charges_total == order.delivery_fee == Decimal("8.00")
    assert order.delivery_details.estimated_delivery_at == setup.now + timedelta(
        minutes=65
    )
    assert (
        order.schedule_calculation.queue_depth == 3
        and order.schedule_calculation.travel_minutes == 30
    )


@pytest.mark.parametrize("subtotal,accept", [("29.99", False), ("30.00", True)])
def test_delivery_minimum_is_on_products_not_fee(setup, subtotal, accept):
    setup.store.addresses[setup.address.id] = (
        setup.cart.guest.customer_id,
        replace(setup.address, district="Juan Guerra"),
    )
    zone = DeliveryZone(
        branch_id=setup.cart.branch,
        name="Paid minimum test",
        district="Juan Guerra",
        delivery_fee=Decimal("10.00"),
    )
    setup.store.zones[zone.id] = zone
    setup.store.settings[setup.cart.branch] = BranchOrderSettings(
        branch_id=setup.cart.branch, delivery_minimum_order=Decimal("30.00")
    )
    setup.cart.catalog_repository.products[setup.cart.product.id] = replace(
        setup.cart.product, base_price=Decimal(subtotal)
    )
    if accept:
        assert create(setup, command=setup.delivery()).subtotal == Decimal(subtotal)
    else:
        with pytest.raises(OrderConflictError) as caught:
            create(setup, command=setup.delivery())
        assert caught.value.code == "DELIVERY_MINIMUM_NOT_MET"
        assert not setup.store.orders


@pytest.mark.parametrize("case", ["coverage", "ownership", "missing"])
def test_delivery_rejection_keeps_cart_active(setup, case):
    if case == "coverage":
        setup.store.addresses[setup.address.id] = (
            setup.cart.guest.customer_id,
            replace(setup.address, district="Unknown"),
        )
    elif case == "ownership":
        setup.store.addresses[setup.address.id] = (uuid4(), setup.address)
    else:
        setup.store.addresses.clear()
    with pytest.raises((OrderConflictError, OrderResourceNotFoundError)) as caught:
        create(setup, command=setup.delivery())
    assert caught.value.code == (
        "DELIVERY_ZONE_UNAVAILABLE"
        if case == "coverage"
        else "DELIVERY_ADDRESS_NOT_FOUND"
    )
    assert next(iter(setup.cart.repository.carts.values())).status == CartStatus.ACTIVE
    assert not setup.store.orders


def test_owner_query_and_newest_first_pagination(setup):
    first = create(setup)
    run(setup.prepare())
    second = create(setup, key="second")
    run(setup.prepare(setup.cart.registered))
    third = create(setup, key="third", principal=setup.cart.registered)
    orders = run(setup.service.list(setup.cart.guest, 100, 0))
    expected = sorted(
        [first, second], key=lambda order: (order.created_at, order.id), reverse=True
    )
    assert [order.id for order in orders] == [order.id for order in expected]
    assert run(setup.service.list(setup.cart.guest, 1, 1)) == expected[1:]
    with pytest.raises(OrderNotFoundError):
        run(setup.service.get(setup.cart.guest, third.id))


def test_admin_settings_table_rotation_and_logical_deletion(setup):
    settings = run(
        setup.admin_service.get_settings(setup.cart.admin, setup.cart.branch)
    )
    assert (
        settings.cash_payment_requires_confirmation
        and settings.default_prep_minutes == 20
    )
    updated = run(
        setup.admin_service.update_settings(
            setup.cart.admin, setup.cart.branch, {"default_prep_minutes": 30}
        )
    )
    assert updated.default_prep_minutes == 30
    rotated = run(
        setup.admin_service.update_table(
            setup.cart.admin,
            setup.cart.branch,
            setup.table.id,
            {"rotate_qr_token": True},
        )
    )
    assert rotated.qr_token != setup.table.qr_token
    run(
        setup.admin_service.deactivate_table(
            setup.cart.admin, setup.cart.branch, setup.table.id
        )
    )
    assert not setup.store.tables[setup.table.id].is_active


def test_admin_cannot_modify_global_free_zone_or_other_branch_resource(setup):
    global_zone = next(iter(setup.store.zones.values()))
    with pytest.raises(OrderResourceNotFoundError):
        run(
            setup.admin_service.update_zone(
                setup.cart.admin,
                setup.cart.branch,
                global_zone.id,
                {"delivery_fee": Decimal("5.00")},
            )
        )
    with pytest.raises(OrderPermissionDeniedError):
        run(
            setup.admin_service.update_settings(
                setup.cart.admin, setup.cart.other_branch, {"default_prep_minutes": 30}
            )
        )


def test_zone_crud_and_duplicate_policy(setup):
    values = {
        "name": "Paid",
        "district": "Juan Guerra",
        "delivery_fee": Decimal("8.00"),
    }
    zone = run(
        setup.admin_service.create_zone(setup.cart.admin, setup.cart.branch, values)
    )
    with pytest.raises(OrderConflictError):
        run(
            setup.admin_service.create_zone(
                setup.cart.admin,
                setup.cart.branch,
                values | {"district": "juan guerra"},
            )
        )
    run(
        setup.admin_service.deactivate_zone(
            setup.cart.admin, setup.cart.branch, zone.id
        )
    )
    assert not setup.store.zones[zone.id].is_active


def test_cash_release_commit_failure_rolls_back_history_and_status(setup):
    order = create(setup)
    setup.session.fail_commit = True
    with pytest.raises(RuntimeError):
        run(setup.service.confirm_cash_release(setup.cart.admin, order.id))
    historical = setup.store.orders[order.id]
    assert historical.status == OrderStatus.PENDING_CASH_CONFIRMATION
    assert historical.payment_status == PaymentStatus.PENDING
    assert len(historical.history) == 1


def test_settings_and_delivery_estimates_do_not_change_past_order(setup):
    order = create(setup, command=setup.delivery())
    run(
        setup.admin_service.update_settings(
            setup.cart.admin,
            setup.cart.branch,
            {"default_prep_minutes": 40, "delivery_default_travel_minutes": 60},
        )
    )
    historical = run(setup.service.get(setup.cart.guest, order.id))
    assert historical.branch_settings_snapshot.default_prep_minutes == 20
    assert (
        historical.delivery_details.estimated_delivery_at
        == order.delivery_details.estimated_delivery_at
    )


def test_long_presentation_names_supported_by_catalog_remain_supported_at_checkout(
    setup,
):
    setup.cart.catalog_repository.presentations[setup.cart.personal.id] = replace(
        setup.cart.personal, name="P" * 150
    )
    assert create(setup).items[0].presentation_name_snapshot == "P" * 150


def test_three_confirmed_queue_orders_increase_configurable_estimate(setup):
    for _ in range(3):
        setup.store.orders[uuid4()] = SimpleNamespace(
            branch_id=setup.cart.branch, status=OrderStatus.WAITING
        )
    estimate = run(
        setup.session.estimate(
            setup.cart.branch,
            BranchOrderSettings(
                branch_id=setup.cart.branch,
                default_prep_minutes=30,
                queue_delay_per_order_minutes=7,
            ),
        )
    )
    assert estimate.queue_depth == 3 and estimate.total_minutes == 51
