"""Device → Delivery locks in every path. Sessions end before provider I/O."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.modules.notifications.application.dtos import PushClaim
from app.modules.notifications.application.errors import NotificationDataError
from app.modules.notifications.domain.models import (
    MAX_PUSH_ATTEMPTS,
    PUSH_LEASE_SECONDS,
    PushResultKind,
    retry_seconds,
)
from app.modules.notifications.domain.models import PushDeliveryStatus as S
from app.modules.notifications.infrastructure.persistence.models import (
    CustomerNotificationModel as N,
)
from app.modules.notifications.infrastructure.persistence.models import (
    NotificationDeviceModel as D,
)
from app.modules.notifications.infrastructure.persistence.models import (
    NotificationPushDeliveryModel as P,
)
from app.modules.notifications.infrastructure.persistence.repositories import (
    cancel_unsent,
    delivery_domain,
    device_domain,
    notification_domain,
)


def due(now):
    return or_(
        and_(P.status == S.PENDING, P.next_attempt_at <= now),
        and_(P.status == S.PROCESSING, P.locked_until < now),
    )


def terminal_values(status, reason=None):
    return {
        "status": status,
        "locked_until": None,
        "claim_token": None,
        "failure_code": reason,
    }


class SQLAlchemyPushRepository:
    def __init__(self, session_factory):
        self.factory = session_factory

    async def claim(self, providers, now, limit):
        try:
            async with self.factory() as session, session.begin():
                candidate = (
                    select(P.id)
                    .where(
                        P.device_id == D.id, P.provider_code.in_(providers), due(now)
                    )
                    .correlate(D)
                    .exists()
                )
                devices = (
                    (
                        await session.execute(
                            select(D)
                            .where(
                                candidate,
                                or_(
                                    D.send_locked_until.is_(None),
                                    D.send_locked_until <= now,
                                ),
                            )
                            .order_by(D.id)
                            .limit(limit)
                            .with_for_update(skip_locked=True)
                            .execution_options(populate_existing=True)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not devices:
                    return []
                by_id = {d.id: d for d in devices}
                rows = (
                    await session.execute(
                        select(P, N)
                        .join(N, N.id == P.notification_id)
                        .where(
                            P.device_id.in_(by_id),
                            P.provider_code.in_(providers),
                            due(now),
                        )
                        .order_by(P.next_attempt_at, P.id)
                        .limit(limit)
                        .with_for_update(of=P, skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                ).all()
                claims = []
                until = now + timedelta(seconds=PUSH_LEASE_SECONDS)
                leased = set()
                for delivery, notification in rows:
                    device = by_id[delivery.device_id]
                    coherent = (
                        device.is_active
                        and device.customer_id == notification.customer_id
                        and device.generation == delivery.device_generation
                        and device.provider_code == delivery.provider_code
                    )
                    if not coherent:
                        await session.execute(
                            update(P)
                            .where(P.id == delivery.id)
                            .values(**terminal_values(S.CANCELLED, "DEVICE_CHANGED"))
                        )
                    elif delivery.attempt_count >= MAX_PUSH_ATTEMPTS:
                        await session.execute(
                            update(P)
                            .where(P.id == delivery.id)
                            .values(**terminal_values(S.FAILED, "MAX_ATTEMPTS"))
                        )
                    else:
                        changed = replace(
                            delivery_domain(delivery),
                            status=S.PROCESSING,
                            attempt_count=delivery.attempt_count + 1,
                            locked_until=until,
                            claim_token=uuid4(),
                            failure_code=None,
                        )
                        await session.execute(
                            update(P)
                            .where(P.id == delivery.id)
                            .values(
                                status=changed.status,
                                attempt_count=changed.attempt_count,
                                locked_until=changed.locked_until,
                                claim_token=changed.claim_token,
                                failure_code=None,
                            )
                        )
                        claims.append(
                            PushClaim(
                                delivery=changed,
                                device=device_domain(device),
                                notification=notification_domain(notification),
                            )
                        )
                        leased.add(device.id)
                for device in devices:
                    await session.execute(
                        update(D)
                        .where(D.id == device.id)
                        .values(
                            send_locked_until=until if device.id in leased else None
                        )
                    )
                return claims
        except SQLAlchemyError:
            raise NotificationDataError() from None

    async def _locked(self, session, claim):
        device = (
            await session.execute(
                select(D)
                .where(D.id == claim.device.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        delivery = (
            await session.execute(
                select(P)
                .where(P.id == claim.delivery.id, P.device_id == claim.device.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return device, delivery

    @staticmethod
    def _current(claim, device, delivery, now):
        return (
            device is not None
            and delivery is not None
            and delivery.status == S.PROCESSING
            and delivery.claim_token == claim.delivery.claim_token
            and delivery.locked_until > now
            and device.is_active
            and device.customer_id == claim.notification.customer_id
            and device.generation == claim.delivery.device_generation
            and device.provider_code == claim.delivery.provider_code
        )

    async def can_send(self, claim, now):
        try:
            async with self.factory() as session, session.begin():
                device, delivery = await self._locked(session, claim)
                return self._current(claim, device, delivery, now)
        except SQLAlchemyError:
            raise NotificationDataError() from None

    async def complete(self, claim, result, now):
        try:
            async with self.factory() as session, session.begin():
                device, delivery = await self._locked(session, claim)
                if not self._current(claim, device, delivery, now):
                    return None  # Old worker must never overwrite a newer lease/token.
                if result.kind == PushResultKind.SENT:
                    values = terminal_values(S.SENT)
                    values |= {
                        "sent_at": now,
                        "provider_message_id": result.provider_message_id,
                    }
                elif result.kind == PushResultKind.INVALID_TOKEN:
                    values = terminal_values(S.FAILED, "INVALID_TOKEN")
                elif result.kind == PushResultKind.PERMANENT_FAILURE:
                    values = terminal_values(S.FAILED, "PERMANENT_FAILURE")
                elif delivery.attempt_count >= MAX_PUSH_ATTEMPTS:
                    values = terminal_values(S.FAILED, "MAX_ATTEMPTS")
                else:
                    values = terminal_values(S.PENDING, "RETRYABLE_FAILURE")
                    values |= {
                        "next_attempt_at": now
                        + timedelta(seconds=retry_seconds(delivery.attempt_count))
                    }
                # Domain validation BEFORE storing trusted adapter fields.
                replace(delivery_domain(delivery), **values)
                await session.execute(
                    update(P)
                    .where(
                        P.id == delivery.id,
                        P.claim_token == claim.delivery.claim_token,
                        P.status == S.PROCESSING,
                    )
                    .values(**values)
                )
                if result.kind == PushResultKind.INVALID_TOKEN:
                    await session.execute(
                        update(D)
                        .where(
                            D.id == device.id,
                            D.generation == claim.delivery.device_generation,
                        )
                        .values(is_active=False, generation=device.generation + 1)
                    )
                    await cancel_unsent(session, device.id, "DEVICE_INACTIVE")
                processing = (
                    await session.execute(
                        select(P.id)
                        .where(P.device_id == device.id, P.status == S.PROCESSING)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if processing is None and result.kind != PushResultKind.INVALID_TOKEN:
                    # Invalidating a token cancels other leases, not provider calls
                    # already in flight. Keep the privacy handoff fence until expiry.
                    await session.execute(
                        update(D)
                        .where(D.id == device.id)
                        .values(send_locked_until=None)
                    )
                return values["status"]
        except SQLAlchemyError:
            raise NotificationDataError() from None
