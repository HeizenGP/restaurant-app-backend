"""Public internal Orders adapter: minimal locked context and atomic paid projection."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)
from app.modules.orders.domain.payments import (
    OrderPaymentContext,
    payment_confirmation_target,
)
from app.modules.orders.infrastructure.persistence.models import (
    OrderModel,
    OrderPickupDetailsModel,
    OrderStatusHistoryModel,
)
from app.modules.orders.infrastructure.persistence.repositories import flush
from app.shared.application.exceptions import DependencyUnavailableError


class SQLAlchemyOrderPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def payment_context(
        self,
        order_id: UUID,
        *,
        customer_id: UUID | None = None,
        branch_id: UUID | None = None,
        lock: bool = False,
    ) -> OrderPaymentContext | None:
        query = (
            select(
                OrderModel.id,
                OrderModel.customer_id,
                OrderModel.branch_id,
                OrderModel.mode,
                OrderModel.status,
                OrderModel.payment_method_type,
                OrderModel.payment_status,
                OrderModel.total,
                OrderModel.confirmed_at,
                OrderPickupDetailsModel.calculated_kitchen_release_at,
            )
            .outerjoin(
                OrderPickupDetailsModel,
                OrderPickupDetailsModel.order_id == OrderModel.id,
            )
            .where(OrderModel.id == order_id)
        )
        if customer_id is not None:
            query = query.where(OrderModel.customer_id == customer_id)
        if branch_id is not None:
            query = query.where(OrderModel.branch_id == branch_id)
        if lock:
            query = query.with_for_update(of=OrderModel)
        row = (await self._session.execute(query)).mappings().one_or_none()
        if row is None:
            return None
        try:
            return OrderPaymentContext(
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
        except (OrderRuleError, ValueError, TypeError):
            raise DependencyUnavailableError(
                "Order payment data is inconsistent"
            ) from None

    async def confirm_payment(
        self, order: OrderPaymentContext, now: datetime, *, online: bool
    ) -> None:
        target = payment_confirmation_target(order, now, online=online)
        if order.payment_status == PaymentStatus.PAID:
            return
        values = {"payment_status": PaymentStatus.PAID}
        if online and target != order.status:
            values.update(status=target, confirmed_at=now)
        row_id = (
            await self._session.execute(
                update(OrderModel)
                .where(
                    OrderModel.id == order.id,
                    OrderModel.branch_id == order.branch_id,
                    OrderModel.customer_id == order.customer_id,
                    OrderModel.status == order.status,
                    OrderModel.payment_status == order.payment_status,
                    OrderModel.payment_method_type == order.payment_method_type,
                    OrderModel.total == order.total,
                )
                .values(**values)
                .returning(OrderModel.id)
            )
        ).scalar_one_or_none()
        if row_id is None:
            raise OrderConflictError("PAYMENT_INVALID_STATE")
        if online and target != order.status:
            history = StatusHistory(
                from_status=order.status,
                to_status=target,
                created_at=now,
                reason="Online payment confirmed",
            )
            self._session.add(
                OrderStatusHistoryModel(order_id=order.id, **asdict(history))
            )
        await flush(self._session)
