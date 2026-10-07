from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.errors import OrderConflictError
from app.modules.orders.domain.cancellations import (
    OrderCancellationContext,
    validate_cancellation,
)
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
    aware,
)
from app.modules.orders.infrastructure.persistence.models import (
    OrderModel,
    OrderStatusHistoryModel,
)
from app.modules.orders.infrastructure.persistence.repositories import flush
from app.shared.application.exceptions import DependencyUnavailableError


class SQLAlchemyOrderCancellationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def context(self, order_id, *, branch_id=None, customer_id=None, lock=False):
        query = select(
            OrderModel.id,
            OrderModel.branch_id,
            OrderModel.customer_id,
            OrderModel.mode,
            OrderModel.status,
            OrderModel.payment_method_type,
            OrderModel.payment_status,
            OrderModel.total,
        ).where(OrderModel.id == order_id)
        if branch_id is not None:
            query = query.where(OrderModel.branch_id == branch_id)
        if customer_id is not None:
            query = query.where(OrderModel.customer_id == customer_id)
        if lock:
            query = query.with_for_update(of=OrderModel)
        row = (await self.session.execute(query)).mappings().one_or_none()
        if row is None:
            return None
        try:
            return OrderCancellationContext(
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
                "Cancellation order data is inconsistent"
            ) from None

    async def cancel(self, order, actor, now, reason):
        validate_cancellation(order)
        aware(now)
        row = (
            await self.session.execute(
                update(OrderModel)
                .where(
                    OrderModel.id == order.id,
                    OrderModel.branch_id == order.branch_id,
                    OrderModel.customer_id == order.customer_id,
                    OrderModel.status == order.status,
                    OrderModel.payment_status == order.payment_status,
                )
                .values(status=OrderStatus.CANCELLED)
                .returning(OrderModel.id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise OrderConflictError("ORDER_NOT_CANCELLABLE")
        history = StatusHistory(
            from_status=order.status,
            to_status=OrderStatus.CANCELLED,
            changed_by_user_id=actor,
            created_at=now,
            reason=reason,
        )
        self.session.add(OrderStatusHistoryModel(order_id=order.id, **asdict(history)))
        await flush(self.session)
