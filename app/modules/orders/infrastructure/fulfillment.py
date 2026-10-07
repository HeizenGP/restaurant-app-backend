"""Public Orders projection and explicit validated transitions. No financial fields."""

from dataclasses import asdict
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.fulfillment import (
    OrderFulfillmentContext,
    validate_fulfillment_transition,
)
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)
from app.modules.orders.infrastructure.persistence.models import (
    OrderDeliveryDetailsModel,
    OrderModel,
    OrderPickupDetailsModel,
    OrderStatusHistoryModel,
)
from app.modules.orders.infrastructure.persistence.repositories import flush
from app.shared.application.exceptions import DependencyUnavailableError


def fulfillment_query():
    o, p, d, h = (
        OrderModel,
        OrderPickupDetailsModel,
        OrderDeliveryDetailsModel,
        OrderStatusHistoryModel,
    )
    history = (
        select(
            func.max(h.created_at)
            .filter(h.to_status == OrderStatus.WAITING)
            .label("waiting_at"),
            func.max(h.created_at)
            .filter(h.to_status == OrderStatus.PREPARING)
            .label("preparing_at"),
            func.max(h.created_at)
            .filter(h.to_status.in_((OrderStatus.READY, OrderStatus.READY_FOR_PICKUP)))
            .label("ready_at"),
            func.max(h.created_at)
            .filter(h.to_status == OrderStatus.OUT_FOR_DELIVERY)
            .label("dispatched_at"),
            func.max(h.created_at)
            .filter(h.to_status == OrderStatus.DELIVERED)
            .label("delivered_at"),
            func.count(h.id)
            .filter(h.to_status == OrderStatus.DELIVERED)
            .label("delivered_history_count"),
        )
        .where(h.order_id == o.id)
        .correlate(o)
        .lateral("fulfillment_history")
    )
    return (
        select(
            o.id,
            o.branch_id,
            o.order_number,
            o.mode,
            o.status,
            o.payment_method_type,
            o.payment_status,
            o.confirmed_at,
            p.requested_pickup_at,
            p.calculated_kitchen_release_at,
            p.estimated_ready_at,
            p.pickup_name_snapshot,
            p.pickup_phone_snapshot,
            d.estimated_delivery_at,
            d.delivery_zone_name_snapshot,
            d.recipient_name_snapshot,
            d.recipient_phone_snapshot,
            d.address_line_snapshot,
            d.reference_text_snapshot,
            d.district_snapshot,
            d.city_snapshot,
            d.department_snapshot,
            *history.c,
        )
        .outerjoin(p, p.order_id == o.id)
        .outerjoin(d, d.order_id == o.id)
        .outerjoin(history, true())
    )


def operational_filters(branch_id, mode):
    return (
        OrderModel.branch_id == branch_id,
        OrderModel.mode == mode,
        OrderModel.payment_method_type == PaymentMethodType.ONLINE,
        OrderModel.payment_status == PaymentStatus.PAID,
        OrderModel.confirmed_at.is_not(None),
    )


def fulfillment_context(row) -> OrderFulfillmentContext:
    try:
        return OrderFulfillmentContext(
            **(
                dict(row)
                | {
                    "mode": OrderMode(row["mode"]),
                    "status": OrderStatus(row["status"]),
                    "payment_method_type": PaymentMethodType(
                        row["payment_method_type"]
                    ),
                    "payment_status": PaymentStatus(row["payment_status"]),
                }
            )
        )
    except (ValueError, TypeError):
        raise DependencyUnavailableError(
            "Fulfillment order data is inconsistent"
        ) from None


class SQLAlchemyOrderFulfillmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_order(self, branch_id: UUID, order_id: UUID):
        row = (
            (
                await self.session.execute(
                    fulfillment_query()
                    .where(OrderModel.branch_id == branch_id, OrderModel.id == order_id)
                    .with_for_update(of=OrderModel)
                )
            )
            .mappings()
            .one_or_none()
        )
        return fulfillment_context(row) if row else None

    async def pickup_candidates(
        self, branch_id, limit, offset=0, *, now=None, prep_minutes=None, lock=False
    ):
        query = fulfillment_query().where(
            *operational_filters(branch_id, OrderMode.PICKUP),
            OrderModel.status == OrderStatus.SCHEDULED,
        )
        if now is not None:
            # Current recommendation; historical release remains untouched.
            query = query.where(
                OrderPickupDetailsModel.requested_pickup_at
                <= now + timedelta(minutes=prep_minutes)
            )
        query = (
            query.order_by(OrderPickupDetailsModel.requested_pickup_at, OrderModel.id)
            .limit(limit)
            .offset(offset)
        )
        if lock:
            query = query.with_for_update(of=OrderModel, skip_locked=True)
        return [
            fulfillment_context(r)
            for r in (await self.session.execute(query)).mappings().all()
        ]

    async def delivery_queue(self, branch_id, status, limit, offset):
        statuses = (
            (status,)
            if status
            else (
                OrderStatus.WAITING,
                OrderStatus.PREPARING,
                OrderStatus.READY,
                OrderStatus.OUT_FOR_DELIVERY,
            )
        )
        query = (
            fulfillment_query()
            .where(
                *operational_filters(branch_id, OrderMode.DELIVERY),
                OrderModel.status.in_(statuses),
            )
            .order_by(OrderModel.order_number, OrderModel.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            fulfillment_context(r)
            for r in (await self.session.execute(query)).mappings().all()
        ]

    async def delay_candidates(self, branch_id, now, limit, after_order_number):
        # Lateral history supplies actual delivered_at in the SAME MVCC snapshot.
        query = fulfillment_query()
        delivered = query.selected_columns.delivered_at
        count = query.selected_columns.delivered_history_count
        deadline = OrderDeliveryDetailsModel.estimated_delivery_at + timedelta(
            minutes=15
        )
        query = (
            query.where(
                *operational_filters(branch_id, OrderMode.DELIVERY),
                OrderModel.order_number > after_order_number,
                or_(
                    and_(
                        OrderModel.status.in_(
                            (
                                OrderStatus.WAITING,
                                OrderStatus.PREPARING,
                                OrderStatus.READY,
                                OrderStatus.OUT_FOR_DELIVERY,
                            )
                        ),
                        deadline < now,
                    ),
                    and_(
                        OrderModel.status == OrderStatus.DELIVERED,
                        or_(delivered > deadline, count != 1),
                    ),
                ),
            )
            .order_by(OrderModel.order_number, OrderModel.id)
            .limit(limit)
            .with_for_update(of=OrderModel, skip_locked=True)
        )
        return [
            fulfillment_context(r)
            for r in (await self.session.execute(query)).mappings().all()
        ]

    async def record_fulfillment_transition(
        self, order: OrderFulfillmentContext, history: StatusHistory
    ) -> None:
        validate_fulfillment_transition(order, history)
        row = (
            await self.session.execute(
                update(OrderModel)
                .where(
                    OrderModel.id == order.id,
                    OrderModel.branch_id == order.branch_id,
                    OrderModel.mode == order.mode,
                    OrderModel.status == order.status,
                    OrderModel.payment_method_type == PaymentMethodType.ONLINE,
                    OrderModel.payment_status == PaymentStatus.PAID,
                    OrderModel.confirmed_at.is_not(None),
                )
                .values(status=history.to_status)
                .returning(OrderModel.id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise OrderConflictError("FULFILLMENT_INVALID_TRANSITION")
        self.session.add(OrderStatusHistoryModel(order_id=order.id, **asdict(history)))
        await flush(self.session)
