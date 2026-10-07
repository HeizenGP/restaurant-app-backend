"""Public local cleanup capability. Caller has the Order lock and authorization."""

from dataclasses import replace

from app.modules.fulfillment.infrastructure.persistence.repositories import (
    SQLAlchemyFulfillmentRepository,
)


class SQLAlchemyFulfillmentCancellationGateway:
    def __init__(self, session):
        self.repository = SQLAlchemyFulfillmentRepository(session)

    async def close_assignment(self, order_id, actor, now):
        current = await self.repository.active_assignment(order_id, lock=True)
        if current is not None:
            await self.repository.close_assignment(
                current,
                replace(
                    current,
                    unassigned_at=now,
                    unassigned_by_user_id=actor,
                    reason="Order cancelled",
                ),
            )
