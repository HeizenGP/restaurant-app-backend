from dataclasses import replace
from uuid import uuid4

import pytest

from app.modules.notifications.application.errors import (
    DeviceBusyError,
    DeviceNotFoundError,
    NotificationNotFoundError,
    PushProviderUnavailableError,
    RealtimePermissionError,
)
from app.modules.notifications.infrastructure.push_gateway import (
    ConfiguredPushGatewayRegistry,
)
from app.shared.application.exceptions import RequestDataError
from tests.modules.notifications.fakes import (
    device,
    enqueue,
    event,
    notification,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("who", ["customer", "guest"])
async def test_owner_read_and_pagination_are_idempotent(setup, who):
    p = getattr(setup, who)
    values = [notification(p.customer_id, setup.branch, i) for i in range(1, 4)]
    for n in values:
        enqueue(setup.store, n)
    enqueue(setup.store, notification(setup.foreign.customer_id, sequence=99))
    page = await setup.service.list_notifications(p, limit=2)
    assert [n.sequence_id for n in page.items] == [3, 2]
    assert page.latest_sequence_id == 3 and page.next_before_sequence_id == 2
    next_page = await setup.service.list_notifications(p, before=2, limit=2)
    assert [n.sequence_id for n in next_page.items] == [1]
    first = await setup.service.mark_read(p, values[0].id)
    setup.clock.advance(10)
    assert await setup.service.mark_read(p, values[0].id) == first
    assert await setup.service.unread_count(p) == 2
    assert await setup.service.mark_all_read(p) == 2
    assert await setup.service.mark_all_read(p) == 0
    assert await setup.service.unread_count(setup.foreign) == 1


async def test_foreign_and_missing_ids_are_indistinguishable(setup):
    n = notification(setup.foreign.customer_id)
    enqueue(setup.store, n)
    for identifier in [n.id, uuid4()]:
        with pytest.raises(NotificationNotFoundError):
            await setup.service.mark_read(setup.customer, identifier)
    assert setup.repo.rollbacks == 2 and n.read_at is None


async def test_failed_commit_rolls_back_read(setup):
    n = notification(setup.customer.customer_id)
    enqueue(setup.store, n)
    setup.repo.fail_commit = True
    with pytest.raises(RuntimeError):
        await setup.service.mark_read(setup.customer, n.id)
    assert setup.store.notifications[n.id].read_at is None
    assert setup.repo.rollbacks == 1


async def test_device_put_repeat_rotate_rebind_and_no_retroactive_delivery(setup):
    installation = uuid4()
    existing = notification(setup.customer.customer_id)
    enqueue(setup.store, existing)
    first = await setup.service.register_device(
        setup.customer, installation, device().platform, "test", "test-token"
    )
    assert not setup.store.deliveries
    assert first == await setup.service.register_device(
        setup.customer, installation, first.platform, "test", "test-token"
    )
    next_n = notification(setup.customer.customer_id, sequence=2)
    enqueue(setup.store, next_n)
    old_pending = next(iter(setup.store.deliveries.values()))
    setup.clock.advance(1)
    rotated = await setup.service.register_device(
        setup.customer, installation, first.platform, "test", "new-token"
    )
    assert rotated.id == first.id and rotated.generation == 2
    assert setup.store.deliveries[old_pending.id].status == "CANCELLED"
    rebound = await setup.service.register_device(
        setup.foreign, installation, first.platform, "test", "another-token"
    )
    assert rebound.id == first.id and rebound.customer_id == setup.foreign.customer_id
    assert rebound.generation == 3
    with pytest.raises(DeviceNotFoundError):
        await setup.service.unregister_device(setup.customer, installation)
    await setup.service.unregister_device(setup.foreign, installation)
    await setup.service.unregister_device(setup.foreign, installation)
    assert not setup.store.devices[first.id].is_active


async def test_inflight_lease_blocks_handoff_but_identical_put_allowed(setup):
    from datetime import timedelta

    d = device(
        setup.customer.customer_id,
        send_locked_until=setup.clock() + timedelta(seconds=120),
    )
    setup.store.devices[d.id] = d
    for p, token in [(setup.foreign, d.push_token), (setup.customer, "rotated")]:
        with pytest.raises(DeviceBusyError):
            await setup.service.register_device(
                p, d.installation_id, d.platform, d.provider_code, token
            )
    assert (
        await setup.service.register_device(
            setup.customer, d.installation_id, d.platform, d.provider_code, d.push_token
        )
        == d
    )
    await setup.service.unregister_device(setup.customer, d.installation_id)
    with pytest.raises(DeviceBusyError):
        await setup.service.register_device(
            setup.foreign, d.installation_id, d.platform, d.provider_code, d.push_token
        )
    setup.clock.advance(121)
    rebound = await setup.service.register_device(
        setup.foreign, d.installation_id, d.platform, d.provider_code, d.push_token
    )
    assert rebound.customer_id == setup.foreign.customer_id


async def test_unconfigured_provider_fails_before_write(setup):
    setup.service.registry = ConfiguredPushGatewayRegistry()
    with pytest.raises(PushProviderUnavailableError):
        await setup.service.register_device(
            setup.customer, uuid4(), device().platform, "test", "test-token"
        )
    assert not setup.store.devices and setup.repo.commits == 0


async def test_read_does_not_cancel_push_or_modify_order_history(setup):
    d = device(setup.customer.customer_id)
    setup.store.devices[d.id] = d
    n = notification(setup.customer.customer_id)
    enqueue(setup.store, n)
    original = dict(setup.store.deliveries)
    await setup.service.mark_read(setup.customer, n.id)
    assert setup.store.deliveries == original


@pytest.mark.parametrize(
    "who,permission",
    [
        ("admin", "ORDER_REALTIME_VIEW"),
        ("admin", "KITCHEN_VIEW"),
        ("kitchen", "KITCHEN_VIEW"),
    ],
)
async def test_permission_exact_scope(setup, who, permission):
    await setup.service.authorize(getattr(setup, who), setup.branch, permission)
    with pytest.raises(RealtimePermissionError):
        await setup.service.authorize(
            getattr(setup, who), setup.other_branch, permission
        )


@pytest.mark.parametrize("who", ["customer", "guest", "foreign", "kitchen"])
async def test_not_admin_realtime(setup, who):
    with pytest.raises(RealtimePermissionError):
        await setup.service.get_admin_snapshot(getattr(setup, who), setup.branch)


async def test_realtime_events_payment_and_terminal_are_not_customer_notifications(
    setup,
):
    e = event(setup.branch, status_changed=True)
    setup.store.events[e.id] = e
    setup.store.events[2] = replace(e, id=2, status=e.status.CANCELLED)
    assert len(await setup.service.list_realtime_events(setup.admin, setup.branch)) == 2
    assert not await setup.service.list_realtime_events(
        setup.admin, setup.branch, after=2
    )
    assert not setup.store.notifications


@pytest.mark.parametrize("limit", [0, -1, 101, True, "1"])
async def test_list_limits(setup, limit):
    with pytest.raises(RequestDataError):
        await setup.service.list_notifications(setup.customer, limit=limit)


@pytest.mark.parametrize("cursor", [-1, 2**63, True, "1"])
async def test_invalid_cursor(setup, cursor):
    with pytest.raises(RequestDataError):
        await setup.service.list_notifications(setup.customer, before=cursor)
