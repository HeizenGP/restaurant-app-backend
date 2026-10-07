"""Operational PostgreSQL projection plus an explicit public Orders adapter."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, case, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.application.errors import KitchenIntegrityError
from app.modules.kitchen.domain.models import (
    KITCHEN_STATUSES,
    KitchenAddon,
    KitchenDataError,
    KitchenItem,
    KitchenOrderSnapshot,
)
from app.modules.orders.domain.lifecycle import OrderTransitionContext
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)
from app.modules.orders.infrastructure.persistence.models import (
    OrderAddonOptionModel,
    OrderDeliveryDetailsModel,
    OrderItemModel,
    OrderLocalDetailsModel,
    OrderModel,
    OrderPickupDetailsModel,
    OrderStatusHistoryModel,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
)


def json_array(aggregate):
    return func.coalesce(aggregate, cast(literal("[]"), JSONB))


def operational_query():
    # Correlated aggregate subqueries keep items/history in the SAME MVCC
    # snapshot as status. No per-card calls, locks, or lazy ORM relationships.
    addon = OrderAddonOptionModel
    item = OrderItemModel
    history = OrderStatusHistoryModel
    addons = (
        select(
            json_array(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "addon_name_snapshot",
                            addon.addon_name_snapshot,
                            "option_name_snapshot",
                            addon.option_name_snapshot,
                        ),
                        addon.created_at,
                        addon.id,
                    )
                )
            )
        )
        .where(addon.order_item_id == item.id)
        .correlate(item)
        .scalar_subquery()
    )
    items = (
        select(
            json_array(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "product_name_snapshot",
                            item.product_name_snapshot,
                            "presentation_name_snapshot",
                            item.presentation_name_snapshot,
                            "quantity",
                            item.quantity,
                            "notes",
                            item.notes,
                            "addon_options",
                            addons,
                        ),
                        item.created_at,
                        item.id,
                    )
                )
            )
        )
        .where(item.order_id == OrderModel.id)
        .correlate(OrderModel)
        .scalar_subquery()
        .label("items")
    )
    histories = (
        select(
            json_array(
                func.jsonb_agg(
                    aggregate_order_by(
                        func.jsonb_build_object(
                            "id",
                            history.id,
                            "from_status",
                            history.from_status,
                            "to_status",
                            history.to_status,
                            "reason",
                            history.reason,
                            "created_at",
                            history.created_at,
                        ),
                        history.created_at,
                        history.id,
                    )
                )
            )
        )
        .where(history.order_id == OrderModel.id)
        .correlate(OrderModel)
        .scalar_subquery()
        .label("history")
    )
    current_entry = (
        select(func.max(history.created_at))
        .where(
            history.order_id == OrderModel.id,
            history.to_status == OrderModel.status,
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )
    query = (
        select(
            OrderModel.id,
            OrderModel.order_number,
            OrderModel.branch_id,
            OrderModel.mode,
            OrderModel.status,
            OrderModel.created_at,
            OrderModel.confirmed_at,
            OrderLocalDetailsModel.table_label_snapshot.label("table_label"),
            OrderPickupDetailsModel.requested_pickup_at,
            OrderPickupDetailsModel.estimated_ready_at,
            OrderDeliveryDetailsModel.estimated_delivery_at,
            items,
            histories,
        )
        .outerjoin(
            OrderLocalDetailsModel, OrderLocalDetailsModel.order_id == OrderModel.id
        )
        .outerjoin(
            OrderPickupDetailsModel, OrderPickupDetailsModel.order_id == OrderModel.id
        )
        .outerjoin(
            OrderDeliveryDetailsModel,
            OrderDeliveryDetailsModel.order_id == OrderModel.id,
        )
        .where(
            OrderModel.status.in_(KITCHEN_STATUSES),
            OrderModel.confirmed_at.is_not(None),
            or_(
                and_(
                    OrderModel.payment_method_type == PaymentMethodType.CASH,
                    OrderModel.mode == OrderMode.LOCAL,
                ),
                and_(
                    OrderModel.payment_method_type == PaymentMethodType.ONLINE,
                    OrderModel.payment_status == PaymentStatus.PAID,
                ),
            ),
            or_(
                OrderModel.status.in_((OrderStatus.WAITING, OrderStatus.PREPARING)),
                and_(
                    OrderModel.status == OrderStatus.READY,
                    OrderModel.mode.in_((OrderMode.LOCAL, OrderMode.DELIVERY)),
                ),
                and_(
                    OrderModel.status == OrderStatus.READY_FOR_PICKUP,
                    OrderModel.mode == OrderMode.PICKUP,
                ),
            ),
        )
    )
    return query, current_entry


def projection(row) -> KitchenOrderSnapshot:
    try:
        items = tuple(
            KitchenItem(
                **(
                    dict(item)
                    | {
                        "addon_options": tuple(
                            KitchenAddon(**option) for option in item["addon_options"]
                        )
                    }
                )
            )
            for item in row["items"]
        )
        history = tuple(
            StatusHistory(
                id=UUID(entry["id"]),
                from_status=OrderStatus(entry["from_status"])
                if entry["from_status"]
                else None,
                to_status=OrderStatus(entry["to_status"]),
                reason=entry["reason"],
                created_at=datetime.fromisoformat(entry["created_at"]),
            )
            for entry in row["history"]
        )
        values = dict(row)
        return KitchenOrderSnapshot(
            **(
                values
                | {
                    "mode": OrderMode(row["mode"]),
                    "status": OrderStatus(row["status"]),
                    "items": items,
                    "history": history,
                }
            )
        )
    except (ValueError, TypeError, KeyError, KitchenDataError):
        raise KitchenIntegrityError() from None


class SQLAlchemyKitchenOrdersGateway:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = SQLAlchemyOrderRepository(session)

    async def queue(
        self, branch_id: UUID, query: KitchenQueueQuery
    ) -> list[KitchenOrderSnapshot]:
        statement, entered_at = operational_query()
        statement = statement.where(OrderModel.branch_id == branch_id)
        if query.mode is not None:
            statement = statement.where(OrderModel.mode == query.mode)
        if query.status is not None:
            statement = statement.where(OrderModel.status == query.status)
        statement = (
            statement.order_by(
                case(
                    (OrderModel.status == OrderStatus.WAITING, 0),
                    (OrderModel.status == OrderStatus.PREPARING, 1),
                    else_=2,
                ),
                entered_at.asc().nullsfirst(),
                OrderModel.order_number,
                OrderModel.id,
            )
            .limit(query.limit + 1)
            .offset(query.offset)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return [projection(row) for row in rows]

    async def get_order(
        self, branch_id: UUID, order_id: UUID
    ) -> KitchenOrderSnapshot | None:
        statement, _ = operational_query()
        row = (
            (
                await self._session.execute(
                    statement.where(
                        OrderModel.branch_id == branch_id, OrderModel.id == order_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return projection(row) if row is not None else None

    async def lock_order(
        self, branch_id: UUID, order_id: UUID
    ) -> OrderTransitionContext | None:
        return await self._orders.lock_preparation_order(branch_id, order_id)

    async def record_preparation_transition(
        self, order: OrderTransitionContext, history: StatusHistory
    ) -> None:
        await self._orders.record_preparation_transition(order, history)

    async def commit(self) -> None:
        await self._orders.commit()

    async def rollback(self) -> None:
        await self._orders.rollback()
