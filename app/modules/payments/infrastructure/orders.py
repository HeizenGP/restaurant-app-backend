from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.domain.payments import OrderPaymentContext
from app.modules.orders.infrastructure.payments import SQLAlchemyOrderPaymentRepository


class SQLAlchemyPaymentOrderLifecycle:
    def __init__(self, session: AsyncSession) -> None:
        self._orders = SQLAlchemyOrderPaymentRepository(session)

    async def owned_context(
        self, customer_id: UUID, order_id: UUID, *, lock: bool
    ) -> OrderPaymentContext | None:
        return await self._orders.payment_context(
            order_id, customer_id=customer_id, lock=lock
        )

    async def branch_context(
        self, branch_id: UUID, order_id: UUID, *, lock: bool
    ) -> OrderPaymentContext | None:
        return await self._orders.payment_context(
            order_id, branch_id=branch_id, lock=lock
        )

    async def lock_context(self, order_id: UUID) -> OrderPaymentContext | None:
        return await self._orders.payment_context(order_id, lock=True)

    async def confirm_paid(
        self, order: OrderPaymentContext, now: datetime, *, online: bool
    ) -> None:
        await self._orders.confirm_payment(order, now, online=online)
