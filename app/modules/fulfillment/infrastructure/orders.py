from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.infrastructure.fulfillment import (
    SQLAlchemyOrderFulfillmentRepository,
)
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
    SQLAlchemyOrderSettingsRepository,
)


class SQLAlchemyFulfillmentOrdersGateway:
    def __init__(self, session: AsyncSession):
        self.orders = SQLAlchemyOrderFulfillmentRepository(session)
        self.settings = SQLAlchemyOrderSettingsRepository(session)
        self.queue = SQLAlchemyOrderRepository(session)

    async def settings_and_queue(self, branch_id):
        return await self.settings.get_settings(
            branch_id
        ), await self.queue.queue_depth(branch_id)

    async def pickup_candidates(self, branch_id, limit, offset=0, **kwargs):
        return await self.orders.pickup_candidates(branch_id, limit, offset, **kwargs)

    async def lock_order(self, branch_id, order_id):
        return await self.orders.lock_order(branch_id, order_id)

    async def delivery_queue(self, branch_id, status, limit, offset):
        return await self.orders.delivery_queue(branch_id, status, limit, offset)

    async def delay_candidates(self, branch_id, now, limit, after_order_number):
        return await self.orders.delay_candidates(
            branch_id, now, limit, after_order_number
        )

    async def transition(self, order, history):
        await self.orders.record_fulfillment_transition(order, history)
