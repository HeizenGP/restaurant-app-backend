from app.modules.orders.infrastructure.cancellations import (
    SQLAlchemyOrderCancellationRepository,
)


class SQLAlchemyCancellationOrdersGateway:
    def __init__(self, session):
        self.orders = SQLAlchemyOrderCancellationRepository(session)

    async def owned(self, customer_id, order_id, *, lock):
        return await self.orders.context(order_id, customer_id=customer_id, lock=lock)

    async def scoped(self, branch_id, order_id, *, lock):
        return await self.orders.context(order_id, branch_id=branch_id, lock=lock)

    async def cancel(self, order, actor, now, reason):
        await self.orders.cancel(order, actor, now, reason)
