from app.modules.payments.infrastructure.refund_registration import (
    SQLAlchemyCancelledOrderRefundRegistrar,
)


class SQLAlchemyCancellationRefundGateway:
    def __init__(self, session):
        self.registration = SQLAlchemyCancelledOrderRefundRegistrar(session)

    async def register_if_paid(self, order, now):
        return await self.registration.register_if_paid(order, now)

    async def for_order(self, order_id):
        return await self.registration.for_order(order_id)
