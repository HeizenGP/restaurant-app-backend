"""Public local obligation capability, used by Cancellations after Order lock."""

from app.modules.orders.domain.models import PaymentStatus as OrdersPaid
from app.modules.payments.application.refund_errors import RefundDataError
from app.modules.payments.application.refund_registration import (
    RefundRegistrationService,
)
from app.modules.payments.domain.models import PaymentStatus
from app.modules.payments.infrastructure.persistence.refund_repositories import (
    SQLAlchemyRefundRepository,
)
from app.modules.payments.infrastructure.persistence.repositories import (
    SQLAlchemyPaymentRepository,
)


class SQLAlchemyCancelledOrderRefundRegistrar:
    def __init__(self, session):
        self.payments = SQLAlchemyPaymentRepository(session)
        self.refunds = SQLAlchemyRefundRepository(session)
        self.registration = RefundRegistrationService(self.refunds)

    async def register_if_paid(self, order, now):
        payment = await self.payments.payment_for_order(order.id, lock=True)
        if order.payment_status != OrdersPaid.PAID:
            if payment is not None and (
                payment.status == PaymentStatus.PAID
                or payment.amount != order.total
                or payment.currency_code != "PEN"
                or payment.method_type != order.payment_method_type
            ):
                raise RefundDataError()
            return None
        if payment is None:
            raise RefundDataError()
        return await self.registration.register_full(
            payment, order.id, order.total, order.payment_method_type, now
        )

    async def for_order(self, order_id):
        return await self.refunds.refund_for_order(order_id, lock=False)
