from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.modules.notifications.application.dtos import (
    AdminOrderSnapshot,
    AdminSnapshot,
    NotificationPage,
)
from app.modules.notifications.application.errors import (
    DeviceBusyError,
    DeviceConflictError,
    NotificationDataError,
)
from app.modules.notifications.domain.models import (
    DevicePlatform,
    Notification,
    NotificationDevice,
    NotificationKind,
    NotificationSource,
    PushDelivery,
    PushDeliveryStatus,
    RealtimeEventType,
    RealtimeOrderEvent,
)
from app.modules.notifications.infrastructure.persistence.models import (
    CustomerNotificationModel as N,
)
from app.modules.notifications.infrastructure.persistence.models import (
    NotificationDeviceModel as D,
)
from app.modules.notifications.infrastructure.persistence.models import (
    NotificationPushDeliveryModel as P,
)
from app.modules.notifications.infrastructure.persistence.models import (
    RealtimeOrderEventModel as E,
)
from app.modules.orders.domain.models import OrderMode, OrderStatus, PaymentStatus
from app.modules.orders.infrastructure.persistence.models import OrderModel as O

ACTIVE_ORDER_STATUSES = tuple(
    s
    for s in OrderStatus
    if s
    not in {
        OrderStatus.CANCELLED,
        OrderStatus.SERVED,
        OrderStatus.PICKED_UP,
        OrderStatus.DELIVERED,
    }
)


def notification_domain(row):
    try:
        return Notification(
            **(
                row.model_dump()
                | {
                    "kind": NotificationKind(row.kind),
                    "source_kind": NotificationSource(row.source_kind),
                    "order_status": OrderStatus(row.order_status)
                    if row.order_status
                    else None,
                }
            )
        )
    except (ValueError, TypeError):
        raise NotificationDataError() from None


def device_domain(row):
    try:
        return NotificationDevice(
            **(row.model_dump() | {"platform": DevicePlatform(row.platform)})
        )
    except (ValueError, TypeError):
        raise NotificationDataError() from None


def delivery_domain(row):
    try:
        return PushDelivery(
            **(row.model_dump() | {"status": PushDeliveryStatus(row.status)})
        )
    except (ValueError, TypeError):
        raise NotificationDataError() from None


def event_domain(row):
    try:
        return RealtimeOrderEvent(
            **(
                row.model_dump()
                | {
                    "mode": OrderMode(row.mode),
                    "event_type": RealtimeEventType(row.event_type),
                    "status": OrderStatus(row.status),
                    "payment_status": PaymentStatus(row.payment_status),
                }
            )
        )
    except (ValueError, TypeError):
        raise NotificationDataError() from None


async def cancel_unsent(session, device_id, reason):
    await session.execute(
        update(P)
        .where(
            P.device_id == device_id,
            P.status.in_((PushDeliveryStatus.PENDING, PushDeliveryStatus.PROCESSING)),
        )
        .values(
            status=PushDeliveryStatus.CANCELLED,
            locked_until=None,
            claim_token=None,
            failure_code=reason,
        )
    )


class SQLAlchemyNotificationRepository:
    def __init__(self, session):
        self.session = session

    async def high_watermark(self, *, customer=None, branch=None):
        if customer is not None:
            query = select(func.coalesce(func.max(N.sequence_id), 0)).where(
                N.customer_id == customer
            )
        elif branch is not None:
            query = select(func.coalesce(func.max(E.id), 0)).where(
                E.branch_id == branch
            )
        else:
            raise NotificationDataError()
        return (await self.session.execute(query)).scalar_one()

    async def list_owned(self, customer, before, limit):
        # Cursor before data: concurrent new commits can only cause harmless replay,
        # never a gap between snapshot and stream. Do not compute MAX after rows.
        watermark = await self.high_watermark(customer=customer)
        query = select(N).where(N.customer_id == customer)
        if before is not None:
            query = query.where(N.sequence_id < before)
        rows = (
            (
                await self.session.execute(
                    query.order_by(N.sequence_id.desc())
                    .limit(limit + 1)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        more = len(rows) > limit
        items = tuple(notification_domain(r) for r in rows[:limit])
        return NotificationPage(
            items=items,
            latest_sequence_id=watermark,
            next_before_sequence_id=items[-1].sequence_id if more and items else None,
        )

    async def unread_count(self, customer):
        return (
            await self.session.execute(
                select(func.count())
                .select_from(N)
                .where(N.customer_id == customer, N.read_at.is_(None))
            )
        ).scalar_one()

    async def mark_read(self, customer, notification, now):
        row = (
            await self.session.execute(
                update(N)
                .where(
                    N.customer_id == customer, N.id == notification, N.read_at.is_(None)
                )
                .values(read_at=func.greatest(now, N.created_at))
                .returning(N)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await self.session.execute(
                    select(N)
                    .where(N.customer_id == customer, N.id == notification)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
        return notification_domain(row) if row else None

    async def mark_all_read(self, customer, now):
        result = await self.session.execute(
            update(N)
            .where(N.customer_id == customer, N.read_at.is_(None))
            .values(read_at=func.greatest(now, N.created_at))
        )
        return max(0, result.rowcount)

    async def register_device(
        self, customer, installation, platform, provider, token, now
    ):
        try:
            row = (
                await self.session.execute(
                    insert(D)
                    .values(
                        installation_id=installation,
                        customer_id=customer,
                        platform=platform,
                        provider_code=provider,
                        push_token=token,
                        is_active=True,
                        generation=1,
                        last_seen_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_notification_devices_installation"
                    )
                    .returning(D)
                )
            ).scalar_one_or_none()
            if row is not None:
                return device_domain(row)
            row = (
                await self.session.execute(
                    select(D)
                    .where(D.installation_id == installation)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            changed = (
                row.customer_id,
                row.platform,
                row.provider_code,
                row.push_token,
                row.is_active,
            ) != (customer, platform, provider, token, True)
            values = {"last_seen_at": now}
            if changed:
                if row.send_locked_until is not None and row.send_locked_until > now:
                    raise DeviceBusyError()
                active = (
                    await self.session.execute(
                        select(P.id)
                        .where(
                            P.device_id == row.id,
                            P.status == PushDeliveryStatus.PROCESSING,
                            P.locked_until > now,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if active is not None:
                    raise DeviceBusyError()
                await cancel_unsent(self.session, row.id, "DEVICE_CHANGED")
                values |= {
                    "customer_id": customer,
                    "platform": platform,
                    "provider_code": provider,
                    "push_token": token,
                    "is_active": True,
                    "generation": row.generation + 1,
                    "send_locked_until": None,
                }
            updated = (
                await self.session.execute(
                    update(D)
                    .where(D.id == row.id)
                    .values(**values)
                    .returning(D)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
            return device_domain(updated)
        except IntegrityError:
            raise DeviceConflictError() from None

    async def unregister_device(self, customer, installation, now):
        row = (
            await self.session.execute(
                select(D)
                .where(D.customer_id == customer, D.installation_id == installation)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        if row.is_active:
            # Keep send_locked_until even when deleting: prevent rebind while an
            # old provider call may be in flight. No physical device deletion.
            await self.session.execute(
                update(D)
                .where(D.id == row.id)
                .values(is_active=False, generation=row.generation + 1)
            )
            await cancel_unsent(self.session, row.id, "DEVICE_INACTIVE")
        return True

    async def admin_snapshot(self, branch, status, after_number, limit):
        watermark = await self.high_watermark(branch=branch)
        query = select(
            O.id.label("order_id"),
            O.order_number,
            O.mode,
            O.status,
            O.payment_status,
            O.customer_name_snapshot,
            O.created_at,
            O.confirmed_at,
            O.updated_at,
        ).where(O.branch_id == branch, O.order_number > after_number)
        query = (
            query.where(O.status == status)
            if status is not None
            else query.where(O.status.in_(ACTIVE_ORDER_STATUSES))
        )
        rows = (
            (
                await self.session.execute(
                    query.order_by(O.order_number, O.id).limit(limit + 1)
                )
            )
            .mappings()
            .all()
        )
        items = tuple(
            AdminOrderSnapshot(
                **(
                    dict(r)
                    | {
                        "mode": OrderMode(r["mode"]),
                        "status": OrderStatus(r["status"]),
                        "payment_status": PaymentStatus(r["payment_status"]),
                    }
                )
            )
            for r in rows[:limit]
        )
        return AdminSnapshot(
            orders=items,
            latest_event_id=watermark,
            next_after_order_number=items[-1].order_number
            if len(rows) > limit and items
            else None,
        )

    async def events(self, branch, after, limit, until=None):
        query = select(E).where(E.branch_id == branch, E.id > after)
        if until is not None:
            query = query.where(E.id <= until)
        return [
            event_domain(r)
            for r in (await self.session.execute(query.order_by(E.id).limit(limit)))
            .scalars()
            .all()
        ]

    async def stream_notifications(self, customer, after, until, limit):
        query = (
            select(N)
            .where(
                N.customer_id == customer, N.sequence_id > after, N.sequence_id <= until
            )
            .order_by(N.sequence_id)
            .limit(limit)
        )
        return [
            notification_domain(r)
            for r in (
                await self.session.execute(
                    query.execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        ]

    async def commit(self):
        try:
            await self.session.commit()
        except IntegrityError:
            raise DeviceConflictError() from None

    async def rollback(self):
        await self.session.rollback()
