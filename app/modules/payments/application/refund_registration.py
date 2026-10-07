"""Local registration only. Caller owns Order/Payment locks and commit."""

from app.modules.payments.application.refund_errors import RefundDataError
from app.modules.payments.application.refund_ports import RefundRegistrationRepository
from app.modules.payments.domain.models import PaymentRuleError
from app.modules.payments.domain.refunds import (
    Refund,
    RefundHistorySource,
    RefundStatus,
    RefundStatusHistory,
    validate_full_refund,
)


class RefundRegistrationService:
    def __init__(self, repository: RefundRegistrationRepository):
        self.repo = repository

    async def register_full(self, payment, order_id, total, method, now):
        try:
            validate_full_refund(payment, order_id, total, method)
        except PaymentRuleError:
            raise RefundDataError() from None
        existing = await self.repo.refund_for_order(order_id, lock=True)
        if existing is not None:
            if (
                existing.payment_id,
                existing.amount,
                existing.currency_code,
                existing.method_type,
            ) != (
                payment.id,
                payment.amount,
                payment.currency_code,
                payment.method_type,
            ):
                raise RefundDataError()
            return existing
        refund = Refund(
            payment_id=payment.id,
            order_id=order_id,
            amount=payment.amount,
            currency_code=payment.currency_code,
            method_type=payment.method_type,
            requested_at=now,
            created_at=now,
            updated_at=now,
        )
        await self.repo.insert_refund(refund)
        await self.repo.append_history(
            RefundStatusHistory(
                refund_id=refund.id,
                from_status=None,
                to_status=RefundStatus.PENDING,
                source=RefundHistorySource.SYSTEM,
                reason="Full cancellation refund obligation registered",
                created_at=now,
            )
        )
        return refund
