from app.modules.fulfillment.infrastructure.cancellations import (
    SQLAlchemyFulfillmentCancellationGateway,
)


class SQLAlchemyCancellationFulfillmentGateway:
    def __init__(self, session):
        self.fulfillment = SQLAlchemyFulfillmentCancellationGateway(session)

    async def close_assignment(self, order_id, actor, now):
        await self.fulfillment.close_assignment(order_id, actor, now)
