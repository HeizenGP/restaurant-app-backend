from collections import defaultdict
from dataclasses import asdict, fields, replace
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.infrastructure.persistence.models import (
    BranchHourModel,
    BranchModel,
)
from app.modules.orders.application.dtos import BranchHours
from app.modules.orders.application.errors import (
    OrderConflictError,
    OrderUniqueConflictError,
)
from app.modules.orders.domain.lifecycle import (
    OrderTransitionContext,
    validate_preparation_transition,
)
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    DeliveryDetails,
    DeliveryZone,
    LocalDetails,
    Order,
    OrderAddonOption,
    OrderItem,
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    PickupDetails,
    RestaurantTable,
    ScheduleCalculation,
    StatusHistory,
)
from app.modules.orders.domain.transitions import QUEUE_STATUSES
from app.modules.orders.infrastructure.persistence.models import (
    BranchOrderSettingsModel,
    DeliveryZoneModel,
    OrderAddonOptionModel,
    OrderDeliveryDetailsModel,
    OrderItemModel,
    OrderLocalDetailsModel,
    OrderModel,
    OrderPickupDetailsModel,
    OrderScheduleCalculationModel,
    OrderStatusHistoryModel,
    RestaurantTableModel,
)


def entity(row, cls):
    values = {field.name: getattr(row, field.name) for field in fields(cls)}
    if cls is LocalDetails:
        values["payment_choice"] = PaymentMethodType(row.payment_choice)
    return cls(**values)


def constraint_name(error: IntegrityError) -> str | None:
    original = error.orig
    for candidate in (original, getattr(original, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if name:
            return name
        diag = getattr(candidate, "diag", None)
        if diag is not None and diag.constraint_name:
            return diag.constraint_name
    return None


async def flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except IntegrityError as error:
        name = constraint_name(error)
        if name in {"uq_orders_source_cart", "uq_orders_customer_idempotency"}:
            raise OrderUniqueConflictError(name) from None
        raise OrderConflictError() from None


def settings_json(settings: BranchOrderSettings) -> dict:
    return {
        name: str(value)
        if isinstance(value, (Decimal, UUID))
        else value.isoformat()
        if isinstance(value, datetime)
        else value
        for name, value in asdict(settings).items()
    }


def settings_from_json(values: dict) -> BranchOrderSettings:
    values = dict(values)
    values["branch_id"] = UUID(values["branch_id"])
    values["delivery_minimum_order"] = Decimal(values["delivery_minimum_order"])
    for name in ("created_at", "updated_at"):
        values[name] = datetime.fromisoformat(values[name])
    return BranchOrderSettings(**values)


class SQLAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _load(self, query) -> list[Order]:
        rows = list(
            (
                await self._session.execute(
                    query.execution_options(populate_existing=True)
                )
            ).scalars()
        )
        if not rows:
            return []
        ids = [row.id for row in rows]
        item_rows = list(
            (
                await self._session.execute(
                    select(OrderItemModel)
                    .where(OrderItemModel.order_id.in_(ids))
                    .order_by(OrderItemModel.created_at, OrderItemModel.id)
                )
            ).scalars()
        )
        options = defaultdict(list)
        if item_rows:
            for option in (
                await self._session.execute(
                    select(OrderAddonOptionModel)
                    .where(
                        OrderAddonOptionModel.order_item_id.in_(
                            [row.id for row in item_rows]
                        )
                    )
                    .order_by(
                        OrderAddonOptionModel.created_at, OrderAddonOptionModel.id
                    )
                )
            ).scalars():
                options[option.order_item_id].append(entity(option, OrderAddonOption))
        items = defaultdict(list)
        for item in item_rows:
            values = {
                field.name: getattr(item, field.name)
                for field in fields(OrderItem)
                if field.name != "addon_options"
            }
            items[item.order_id].append(
                OrderItem(**values, addon_options=tuple(options[item.id]))
            )
        history = defaultdict(list)
        for row in (
            await self._session.execute(
                select(OrderStatusHistoryModel)
                .where(OrderStatusHistoryModel.order_id.in_(ids))
                .order_by(
                    OrderStatusHistoryModel.created_at, OrderStatusHistoryModel.id
                )
            )
        ).scalars():
            history[row.order_id].append(
                StatusHistory(
                    **{
                        field.name: getattr(row, field.name)
                        for field in fields(StatusHistory)
                        if field.name not in {"from_status", "to_status"}
                    },
                    from_status=OrderStatus(row.from_status)
                    if row.from_status
                    else None,
                    to_status=OrderStatus(row.to_status),
                )
            )
        details = {}
        for model, cls, name in (
            (OrderLocalDetailsModel, LocalDetails, "local_details"),
            (OrderPickupDetailsModel, PickupDetails, "pickup_details"),
            (OrderDeliveryDetailsModel, DeliveryDetails, "delivery_details"),
            (
                OrderScheduleCalculationModel,
                ScheduleCalculation,
                "schedule_calculation",
            ),
        ):
            detail_rows = (
                await self._session.execute(
                    select(model).where(model.order_id.in_(ids))
                )
            ).scalars()
            details[name] = {row.order_id: entity(row, cls) for row in detail_rows}
        orders = []
        nested = {"items", "history", "branch_settings_snapshot", *details.keys()}
        for row in rows:
            values = {
                field.name: getattr(row, field.name)
                for field in fields(Order)
                if field.name not in nested
            }
            values.update(
                mode=OrderMode(row.mode),
                status=OrderStatus(row.status),
                payment_method_type=PaymentMethodType(row.payment_method_type),
                payment_status=PaymentStatus(row.payment_status),
            )
            orders.append(
                Order(
                    **values,
                    items=tuple(items[row.id]),
                    history=tuple(history[row.id]),
                    branch_settings_snapshot=settings_from_json(
                        row.branch_settings_snapshot
                    ),
                    **{name: mapping.get(row.id) for name, mapping in details.items()},
                )
            )
        return orders

    async def by_idempotency(self, customer_id: UUID, key: str) -> Order | None:
        rows = await self._load(
            select(OrderModel).where(
                OrderModel.customer_id == customer_id,
                OrderModel.idempotency_key == key,
            )
        )
        return rows[0] if rows else None

    async def get_owned(self, customer_id: UUID, order_id: UUID) -> Order | None:
        rows = await self._load(
            select(OrderModel).where(
                OrderModel.id == order_id,
                OrderModel.customer_id == customer_id,
            )
        )
        return rows[0] if rows else None

    async def list_owned(
        self, customer_id: UUID, limit: int, offset: int
    ) -> list[Order]:
        return await self._load(
            select(OrderModel)
            .where(OrderModel.customer_id == customer_id)
            .order_by(OrderModel.created_at.desc(), OrderModel.id.desc())
            .limit(limit)
            .offset(offset)
        )

    async def lock_order(self, order_id: UUID) -> Order | None:
        rows = await self._load(
            select(OrderModel).where(OrderModel.id == order_id).with_for_update()
        )
        return rows[0] if rows else None

    async def lock_preparation_order(
        self, branch_id: UUID, order_id: UUID
    ) -> OrderTransitionContext | None:
        """Public internal contract: branch-scoped, minimal and serialized."""
        row = (
            (
                await self._session.execute(
                    select(
                        OrderModel.id,
                        OrderModel.branch_id,
                        OrderModel.mode,
                        OrderModel.status,
                        OrderModel.payment_method_type,
                        OrderModel.payment_status,
                        OrderModel.confirmed_at,
                    )
                    .where(OrderModel.id == order_id, OrderModel.branch_id == branch_id)
                    .with_for_update(of=OrderModel)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return OrderTransitionContext(
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

    async def record_preparation_transition(
        self, order: OrderTransitionContext, history: StatusHistory
    ) -> None:
        """Orders validates its graph; caller owns the lock and transaction."""
        validate_preparation_transition(order, history)
        result = await self._session.execute(
            update(OrderModel)
            .where(
                OrderModel.id == order.id,
                OrderModel.branch_id == order.branch_id,
                OrderModel.status == order.status,
                OrderModel.mode == order.mode,
                OrderModel.payment_method_type == order.payment_method_type,
                OrderModel.payment_status == order.payment_status,
                OrderModel.confirmed_at.is_not(None),
            )
            .values(status=history.to_status)
            .returning(OrderModel.id)
        )
        if result.scalar_one_or_none() is None:
            raise OrderConflictError("KITCHEN_INVALID_TRANSITION")
        self._session.add(OrderStatusHistoryModel(order_id=order.id, **asdict(history)))
        await flush(self._session)

    async def create(self, order: Order) -> Order:
        nested = {
            "items",
            "history",
            "local_details",
            "pickup_details",
            "delivery_details",
            "schedule_calculation",
            "branch_settings_snapshot",
            "order_number",
        }
        values = {
            field.name: getattr(order, field.name)
            for field in fields(Order)
            if field.name not in nested
        }
        row = OrderModel(
            **values,
            branch_settings_snapshot=settings_json(order.branch_settings_snapshot),
        )
        self._session.add(row)
        await flush(self._session)
        await self._session.refresh(row)
        for item in order.items:
            values = {
                field.name: getattr(item, field.name)
                for field in fields(OrderItem)
                if field.name != "addon_options"
            }
            self._session.add(OrderItemModel(order_id=order.id, **values))
        await flush(self._session)
        for item in order.items:
            for option in item.addon_options:
                self._session.add(
                    OrderAddonOptionModel(order_item_id=item.id, **asdict(option))
                )
        for detail, model in (
            (order.local_details, OrderLocalDetailsModel),
            (order.pickup_details, OrderPickupDetailsModel),
            (order.delivery_details, OrderDeliveryDetailsModel),
            (order.schedule_calculation, OrderScheduleCalculationModel),
        ):
            if detail is not None:
                self._session.add(model(order_id=order.id, **asdict(detail)))
        for history in order.history:
            self._session.add(
                OrderStatusHistoryModel(order_id=order.id, **asdict(history))
            )
        await flush(self._session)
        return replace(
            order,
            order_number=row.order_number,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def release_cash(self, order: Order, history: StatusHistory) -> Order:
        result = await self._session.execute(
            update(OrderModel)
            .where(
                OrderModel.id == order.id,
                OrderModel.status == OrderStatus.PENDING_CASH_CONFIRMATION,
                OrderModel.mode == OrderMode.LOCAL,
                OrderModel.payment_method_type == PaymentMethodType.CASH,
            )
            .values(status=OrderStatus.WAITING, confirmed_at=history.created_at)
            .returning(OrderModel.updated_at)
        )
        updated_at = result.scalar_one_or_none()
        if updated_at is None:
            raise OrderConflictError("CASH_RELEASE_NOT_ALLOWED")
        self._session.add(OrderStatusHistoryModel(order_id=order.id, **asdict(history)))
        await flush(self._session)
        return replace(
            order,
            status=OrderStatus.WAITING,
            confirmed_at=history.created_at,
            updated_at=updated_at,
            history=(*order.history, history),
        )

    async def queue_depth(self, branch_id: UUID) -> int:
        return (
            await self._session.execute(
                select(func.count())
                .select_from(OrderModel)
                .where(
                    OrderModel.branch_id == branch_id,
                    OrderModel.status.in_(QUEUE_STATUSES),
                )
            )
        ).scalar_one()

    async def pickup_due_for_release(
        self, now: datetime, limit: int = 100
    ) -> list[Order]:
        """Future scheduler query, not a Kitchen dispatcher."""
        return await self._load(
            select(OrderModel)
            .join(
                OrderPickupDetailsModel,
                OrderPickupDetailsModel.order_id == OrderModel.id,
            )
            .where(
                OrderModel.status == OrderStatus.SCHEDULED,
                OrderModel.mode == OrderMode.PICKUP,
                OrderModel.payment_status == PaymentStatus.PAID,
                OrderPickupDetailsModel.calculated_kitchen_release_at <= now,
            )
            .order_by(
                OrderPickupDetailsModel.calculated_kitchen_release_at, OrderModel.id
            )
            .limit(limit)
        )

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as error:
            raise OrderUniqueConflictError(constraint_name(error)) from None

    async def rollback(self) -> None:
        await self._session.rollback()


class SQLAlchemyOrderSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def branch_is_active(self, branch_id: UUID) -> bool:
        return (
            await self._session.execute(
                select(BranchModel.id).where(
                    BranchModel.id == branch_id,
                    BranchModel.is_active.is_(True),
                    BranchModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none() is not None

    async def get_settings(
        self, branch_id: UUID, *, lock: bool = False, for_update: bool = False
    ) -> BranchOrderSettings:
        branch_timezone = "America/Lima"
        if lock:
            # Branch lock also covers the absence of a settings row. Checkout
            # takes SHARE; admin takes UPDATE. No lock upgrades during checkout.
            branch_result = await self._session.execute(
                select(BranchModel.timezone)
                .where(BranchModel.id == branch_id)
                .with_for_update(read=not for_update)
            )
            branch_timezone = branch_result.scalar_one_or_none() or branch_timezone
        query = select(BranchOrderSettingsModel).where(
            BranchOrderSettingsModel.branch_id == branch_id
        )
        if lock:
            query = query.with_for_update(read=not for_update)
        row = (
            await self._session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        if row:
            return entity(row, BranchOrderSettings)
        if not lock:
            branch_timezone = (
                await self._session.execute(
                    select(BranchModel.timezone).where(BranchModel.id == branch_id)
                )
            ).scalar_one_or_none() or branch_timezone
        return BranchOrderSettings(branch_id=branch_id, timezone=branch_timezone)

    async def save_settings(self, settings: BranchOrderSettings) -> BranchOrderSettings:
        values = asdict(settings)
        statement = (
            insert(BranchOrderSettingsModel)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["branch_id"],
                set_={
                    name: value
                    for name, value in values.items()
                    if name not in {"branch_id", "created_at", "updated_at"}
                },
            )
            .returning(BranchOrderSettingsModel)
        )
        row = (
            await self._session.execute(
                statement.execution_options(populate_existing=True)
            )
        ).scalar_one()
        return entity(row, BranchOrderSettings)

    async def branch_hours(self, branch_id: UUID) -> BranchHours:
        rows = (
            await self._session.execute(
                select(BranchHourModel)
                .where(BranchHourModel.branch_id == branch_id)
                .order_by(BranchHourModel.day_of_week)
                .with_for_update(read=True)
            )
        ).scalars()
        return BranchHours(
            tuple(
                (row.day_of_week, row.open_time, row.close_time, row.is_closed)
                for row in rows
            )
        )

    async def table_by_qr(self, qr_token: UUID) -> RestaurantTable | None:
        row = (
            await self._session.execute(
                select(RestaurantTableModel)
                .where(
                    RestaurantTableModel.qr_token == qr_token,
                    RestaurantTableModel.is_active.is_(True),
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return entity(row, RestaurantTable) if row else None

    async def list_tables(self, branch_id: UUID) -> list[RestaurantTable]:
        rows = (
            await self._session.execute(
                select(RestaurantTableModel)
                .where(RestaurantTableModel.branch_id == branch_id)
                .order_by(RestaurantTableModel.label, RestaurantTableModel.id)
            )
        ).scalars()
        return [entity(row, RestaurantTable) for row in rows]

    async def get_table(
        self, branch_id: UUID, table_id: UUID
    ) -> RestaurantTable | None:
        row = (
            await self._session.execute(
                select(RestaurantTableModel)
                .where(
                    RestaurantTableModel.branch_id == branch_id,
                    RestaurantTableModel.id == table_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return entity(row, RestaurantTable) if row else None

    async def save_table(self, table: RestaurantTable) -> RestaurantTable:
        row = await self._session.get(RestaurantTableModel, table.id)
        if row is None:
            row = RestaurantTableModel(**asdict(table))
            self._session.add(row)
        else:
            row.label, row.is_active, row.qr_token = (
                table.label,
                table.is_active,
                table.qr_token,
            )
        await flush(self._session)
        await self._session.refresh(row)
        return entity(row, RestaurantTable)

    async def resolve_zone(self, branch_id: UUID, district: str) -> DeliveryZone | None:
        query = (
            select(DeliveryZoneModel)
            .where(
                DeliveryZoneModel.district == district.strip(),
                DeliveryZoneModel.is_active.is_(True),
                or_(
                    DeliveryZoneModel.branch_id == branch_id,
                    DeliveryZoneModel.branch_id.is_(None),
                ),
            )
            .order_by(
                case(
                    (
                        (DeliveryZoneModel.branch_id.is_(None))
                        & DeliveryZoneModel.is_free.is_(True),
                        0,
                    ),
                    (DeliveryZoneModel.branch_id == branch_id, 1),
                    else_=2,
                ),
                DeliveryZoneModel.id,
            )
            .limit(1)
            .with_for_update(read=True)
        )
        row = (
            await self._session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return entity(row, DeliveryZone) if row else None

    async def list_zones(self, branch_id: UUID) -> list[DeliveryZone]:
        rows = (
            await self._session.execute(
                select(DeliveryZoneModel)
                .where(
                    or_(
                        DeliveryZoneModel.branch_id == branch_id,
                        DeliveryZoneModel.branch_id.is_(None),
                    )
                )
                .order_by(DeliveryZoneModel.district, DeliveryZoneModel.id)
            )
        ).scalars()
        return [entity(row, DeliveryZone) for row in rows]

    async def get_zone(self, branch_id: UUID, zone_id: UUID) -> DeliveryZone | None:
        row = (
            await self._session.execute(
                select(DeliveryZoneModel)
                .where(
                    DeliveryZoneModel.id == zone_id,
                    DeliveryZoneModel.branch_id == branch_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return entity(row, DeliveryZone) if row else None

    async def save_zone(self, zone: DeliveryZone) -> DeliveryZone:
        row = await self._session.get(DeliveryZoneModel, zone.id)
        if row is None:
            row = DeliveryZoneModel(**asdict(zone))
            self._session.add(row)
        else:
            for name in (
                "name",
                "district",
                "is_free",
                "delivery_fee",
                "estimated_travel_minutes",
                "is_active",
            ):
                setattr(row, name, getattr(zone, name))
        await flush(self._session)
        await self._session.refresh(row)
        return entity(row, DeliveryZone)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
