"""Use cases: owner-scoped reads, branch cash, and authenticated financial events."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
)
from app.modules.orders.domain.models import (
    PaymentStatus as OrderPaymentStatus,
)
from app.modules.orders.domain.payments import OrderPaymentContext
from app.modules.payments.application.dtos import (
    GatewayAttemptRequest,
    OnlineInitiation,
    PaymentView,
)
from app.modules.payments.application.errors import (
    PaymentCashPermissionDeniedError,
    PaymentConflictError,
    PaymentDataError,
    PaymentEventInvalidError,
    PaymentEventPendingError,
    PaymentNotFoundError,
    PaymentProviderUnavailableError,
)
from app.modules.payments.application.ports import (
    OnlinePaymentGateway,
    PaymentAuthorization,
    PaymentOrderLifecycle,
    PaymentRepository,
)
from app.modules.payments.domain.models import (
    BUSINESS_CURRENCY,
    AttemptStatus,
    EventStatus,
    HistorySource,
    Payment,
    PaymentAttempt,
    PaymentRuleError,
    PaymentStatus,
    PaymentStatusHistory,
    ProviderEvent,
    VerifiedResult,
    idempotency_key,
)
from app.modules.payments.domain.transitions import (
    transition_attempt,
    transition_payment,
)
from app.shared.application.exceptions import ForbiddenError, RequestDataError
from app.shared.domain.time import utc_now

MAX_WEBHOOK_BYTES = 65536
CASH_PERMISSION = "PAYMENT_CASH_MANAGE"


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepository,
        orders: PaymentOrderLifecycle,
        authorization: PaymentAuthorization,
        gateway: OnlinePaymentGateway,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.repository = repository
        self.orders = orders
        self.authorization = authorization
        self.gateway = gateway
        self.clock = clock

    @staticmethod
    def _customer(principal: Principal) -> UUID:
        if principal.customer_id is None:
            raise ForbiddenError("Customer identity required")
        return principal.customer_id

    @staticmethod
    def _consistent(payment: Payment, order: OrderPaymentContext) -> None:
        if (
            payment.order_id != order.id
            or payment.amount != order.total
            or payment.currency_code != BUSINESS_CURRENCY
            or payment.method_type != order.payment_method_type
            or (payment.status == PaymentStatus.PAID)
            != (order.payment_status == OrderPaymentStatus.PAID)
        ):
            raise PaymentDataError()

    async def _new_payment(self, order: OrderPaymentContext, now: datetime) -> Payment:
        if order.payment_status != OrderPaymentStatus.PENDING:
            # Never fabricate provenance for a legacy paid order.
            raise PaymentDataError()
        payment = Payment(
            order_id=order.id,
            method_type=order.payment_method_type,
            amount=order.total,
            created_at=now,
            updated_at=now,
        )
        await self.repository.insert_payment(payment)
        await self.repository.append_history(
            PaymentStatusHistory(
                payment_id=payment.id,
                from_status=None,
                to_status=PaymentStatus.PENDING,
                source=HistorySource.SYSTEM,
                reason="Payment ledger created",
                created_at=now,
            )
        )
        return payment

    async def _change(
        self,
        payment: Payment,
        target: PaymentStatus,
        now: datetime,
        *,
        source: HistorySource,
        attempt: PaymentAttempt | None = None,
        actor: UUID | None = None,
        event_id: str | None = None,
    ) -> Payment:
        updated = await self.repository.save_payment(
            payment, transition_payment(payment, target, now)
        )
        await self.repository.append_history(
            PaymentStatusHistory(
                payment_id=payment.id,
                payment_attempt_id=attempt.id if attempt else None,
                from_status=payment.status,
                to_status=target,
                source=source,
                changed_by_user_id=actor,
                provider_event_id=event_id,
                reason="Financial state confirmed",
                created_at=now,
            )
        )
        return updated

    async def get(self, principal: Principal, order_id: UUID) -> PaymentView:
        view = await self.repository.get_owned(self._customer(principal), order_id)
        if view is None:
            raise PaymentNotFoundError()
        return view

    async def confirm_cash(
        self, principal: Principal, branch_id: UUID, order_id: UUID
    ) -> PaymentView:
        try:
            if (
                principal.principal_type != PrincipalType.REGISTERED
                or principal.user_id is None
                or not await self.authorization.has_permission(
                    principal.user_id, branch_id, CASH_PERMISSION
                )
            ):
                raise PaymentCashPermissionDeniedError()
            order = await self.orders.branch_context(branch_id, order_id, lock=True)
            if order is None:
                raise PaymentNotFoundError(order=True)
            if (
                order.mode != OrderMode.LOCAL
                or order.payment_method_type != PaymentMethodType.CASH
            ):
                raise PaymentConflictError("PAYMENT_METHOD_INVALID")
            if order.status == OrderStatus.CANCELLED:
                raise PaymentConflictError()
            now = self.clock()
            payment = await self.repository.payment_for_order(order_id, lock=True)
            if payment is None:
                payment = await self._new_payment(order, now)
            self._consistent(payment, order)
            if payment.status != PaymentStatus.PAID:
                payment = await self._change(
                    payment,
                    PaymentStatus.PAID,
                    now,
                    source=HistorySource.STAFF,
                    actor=principal.user_id,
                )
                await self.orders.confirm_paid(order, now, online=False)
            view = await self.repository.view(payment)
            await self.repository.commit()
            return view
        except Exception:
            await self.repository.rollback()
            raise

    async def initiate_online(
        self, principal: Principal, order_id: UUID, key: str
    ) -> OnlineInitiation:
        try:
            idempotency_key(key)
        except PaymentRuleError:
            raise RequestDataError("Invalid payment idempotency key") from None
        try:
            reserved = await self._reserve(principal, order_id, key)
        except Exception:
            await self.repository.rollback()
            raise
        if isinstance(reserved, OnlineInitiation):
            return reserved
        payment, attempt = reserved
        # The DB reservation is committed. No locks or open transaction cross this call.
        try:
            result = await self.gateway.create_payment_attempt(
                GatewayAttemptRequest(
                    order_id=order_id,
                    payment_id=payment.id,
                    attempt_id=attempt.id,
                    amount=payment.amount,
                    currency_code=payment.currency_code,
                    provider_idempotency_key="payment-attempt:" + str(attempt.id),
                )
            )
            if result.provider_code != attempt.provider_code:
                raise PaymentProviderUnavailableError()
        except (OSError, TimeoutError, PaymentRuleError):
            # Ambiguous network failures must remain recoverable, not become "declines".
            raise PaymentProviderUnavailableError() from None
        try:
            order = await self.orders.lock_context(order_id)
            current = await self.repository.payment_for_order(order_id, lock=True)
            current_attempt = await self.repository.attempt_by_id(
                payment.id, attempt.id, lock=True
            )
            if order is None or current is None or current_attempt is None:
                raise PaymentDataError()
            self._consistent(current, order)
            if current_attempt.provider_reference is not None and (
                result.provider_reference != current_attempt.provider_reference
            ):
                raise PaymentConflictError("PAYMENT_IDEMPOTENCY_CONFLICT")
            if current_attempt.status == AttemptStatus.CREATED:
                current_attempt = await self.repository.save_attempt(
                    current_attempt,
                    transition_attempt(
                        current_attempt,
                        result.status,
                        self.clock(),
                        provider_reference=result.provider_reference,
                        client_action=result.client_action,
                        # Persist a safe category, never a provider message.
                        failure_code="PAYMENT_DECLINED"
                        if result.status == AttemptStatus.FAILED
                        else None,
                    ),
                )
                if (
                    result.status == AttemptStatus.FAILED
                    and current.status == PaymentStatus.PROCESSING
                ):
                    current = await self._change(
                        current,
                        PaymentStatus.FAILED,
                        self.clock(),
                        source=HistorySource.SYSTEM,
                        attempt=current_attempt,
                    )
            response = await self._initiation(current, current_attempt)
            await self.repository.commit()
            return response
        except Exception:
            await self.repository.rollback()
            raise

    async def _reserve(
        self, principal: Principal, order_id: UUID, key: str
    ) -> OnlineInitiation | tuple[Payment, PaymentAttempt]:
        order = await self.orders.owned_context(
            self._customer(principal), order_id, lock=True
        )
        if order is None:
            raise PaymentNotFoundError(order=True)
        if order.payment_method_type != PaymentMethodType.ONLINE:
            raise PaymentConflictError("PAYMENT_METHOD_INVALID")
        payment = await self.repository.payment_for_order(order_id, lock=True)
        if payment is not None:
            self._consistent(payment, order)
            attempt = await self.repository.attempt_by_key(payment.id, key)
            if attempt is not None and (
                attempt.status != AttemptStatus.CREATED
                or payment.status == PaymentStatus.PAID
            ):
                response = await self._initiation(payment, attempt)
                await self.repository.commit()
                return response
            if payment.status == PaymentStatus.PAID:
                raise PaymentConflictError()
        else:
            attempt = None
        if (
            order.status != OrderStatus.PENDING_PAYMENT
            or order.payment_status != OrderPaymentStatus.PENDING
        ):
            raise PaymentConflictError()
        if payment is not None:
            active = await self.repository.active_attempt(payment.id)
            if active is not None and (attempt is None or active.id != attempt.id):
                raise PaymentConflictError("PAYMENT_IDEMPOTENCY_CONFLICT")
        # Resolve configuration only AFTER ownership, BEFORE any new writes.
        provider = self.gateway.provider_code
        now = self.clock()
        if payment is None:
            payment = await self._new_payment(order, now)
        if attempt is None:
            if payment.status not in {PaymentStatus.PENDING, PaymentStatus.FAILED}:
                raise PaymentConflictError()
            attempt = PaymentAttempt(
                payment_id=payment.id,
                idempotency_key=key,
                provider_code=provider,
                amount=payment.amount,
                created_at=now,
                updated_at=now,
            )
            await self.repository.insert_attempt(attempt)
            payment = await self._change(
                payment,
                PaymentStatus.PROCESSING,
                now,
                source=HistorySource.CUSTOMER,
                actor=principal.user_id,
                attempt=attempt,
            )
        elif (
            attempt.provider_code != provider
            or payment.status != PaymentStatus.PROCESSING
        ):
            raise PaymentConflictError()
        await self.repository.commit()
        return payment, attempt

    async def _initiation(
        self, payment: Payment, attempt: PaymentAttempt
    ) -> OnlineInitiation:
        return OnlineInitiation(
            payment=await self.repository.view(payment),
            attempt=attempt,
            client_action=attempt.client_action
            if payment.status != PaymentStatus.PAID
            else None,
        )

    async def webhook(
        self, provider: str, raw_body: bytes, headers: Mapping[str, str]
    ) -> None:
        if len(raw_body) > MAX_WEBHOOK_BYTES:
            raise PaymentEventInvalidError()
        # Sole trust boundary: customer JSON cannot construct a paid command.
        try:
            verified = await self.gateway.verify_and_parse_webhook(
                provider, raw_body, headers
            )
        except PaymentRuleError:
            raise PaymentEventInvalidError() from None
        except (OSError, TimeoutError):
            raise PaymentProviderUnavailableError() from None
        if verified.provider_code != provider:
            raise PaymentEventInvalidError()
        incoming = ProviderEvent(
            provider_code=provider,
            provider_event_id=verified.provider_event_id,
            provider_reference=verified.provider_reference,
            result=verified.result,
            reported_amount=verified.amount,
            reported_currency=verified.currency_code,
            provider_occurred_at=verified.occurred_at,
            event_type=verified.event_type,
            payload_hash=sha256(raw_body).hexdigest(),
            received_at=self.clock(),
        )
        try:
            event = await self.repository.get_or_insert_event(incoming)
            if event.payload_hash != incoming.payload_hash:
                raise PaymentConflictError("PAYMENT_PROVIDER_EVENT_INVALID")
            if event.processing_status != EventStatus.RECEIVED and not (
                event.processing_status == EventStatus.REJECTED
                and event.reason_code == "UNKNOWN_REFERENCE"
            ):
                await self.repository.commit()
                return
            locator = await self.repository.attempt_locator(
                provider, event.provider_reference
            )
            pending_correlation = locator is None
            if locator is None:
                await self._finish_event(
                    event, EventStatus.REJECTED, "UNKNOWN_REFERENCE"
                )
            else:
                order = await self.orders.lock_context(locator.order_id)
                payment = await self.repository.payment_for_order(
                    locator.order_id, lock=True
                )
                attempt = await self.repository.attempt_by_id(
                    locator.payment_id, locator.attempt_id, lock=True
                )
                if order is None or payment is None or attempt is None:
                    raise PaymentDataError()
                self._consistent(payment, order)
                if (
                    payment.id != locator.payment_id
                    or attempt.payment_id != payment.id
                    or payment.method_type != PaymentMethodType.ONLINE
                    or attempt.provider_code != provider
                    or attempt.provider_reference != event.provider_reference
                ):
                    raise PaymentDataError()
                event = replace(event, payment_attempt_id=attempt.id)
                if (
                    event.reported_amount != attempt.amount
                    or attempt.amount != payment.amount
                ):
                    await self._finish_event(
                        event, EventStatus.REJECTED, "AMOUNT_MISMATCH"
                    )
                elif event.reported_currency != payment.currency_code:
                    await self._finish_event(
                        event, EventStatus.REJECTED, "CURRENCY_MISMATCH"
                    )
                elif event.result == VerifiedResult.FAILED:
                    await self._failure(event, payment, attempt)
                else:
                    await self._success(event, order, payment, attempt)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
        if pending_correlation:
            # Evidence is committed, but do not acknowledge a charge we cannot
            # correlate yet. The adapter/provider must support delivery retries.
            raise PaymentEventPendingError()

    async def _finish_event(
        self, event: ProviderEvent, status: EventStatus, reason: str | None = None
    ) -> None:
        await self.repository.save_event(
            event,
            replace(
                event,
                processing_status=status,
                processed_at=self.clock(),
                reason_code=reason,
            ),
        )

    async def _failure(
        self, event: ProviderEvent, payment: Payment, attempt: PaymentAttempt
    ) -> None:
        if payment.status == PaymentStatus.PAID or attempt.status in {
            AttemptStatus.SUCCEEDED,
            AttemptStatus.FAILED,
        }:
            await self._finish_event(event, EventStatus.IGNORED, "STALE_FAILURE")
            return
        attempt = await self.repository.save_attempt(
            attempt,
            transition_attempt(
                attempt,
                AttemptStatus.FAILED,
                self.clock(),
                failure_code="PAYMENT_DECLINED",
            ),
        )
        if (
            payment.status == PaymentStatus.PROCESSING
            and await self.repository.active_attempt(payment.id) is None
        ):
            await self._change(
                payment,
                PaymentStatus.FAILED,
                self.clock(),
                source=HistorySource.PROVIDER,
                attempt=attempt,
                event_id=event.provider_event_id,
            )
        await self._finish_event(event, EventStatus.PROCESSED)

    async def _success(
        self,
        event: ProviderEvent,
        order: OrderPaymentContext,
        payment: Payment,
        attempt: PaymentAttempt,
    ) -> None:
        if attempt.status == AttemptStatus.SUCCEEDED:
            if payment.status != PaymentStatus.PAID:
                raise PaymentDataError()
            if order.status == OrderStatus.CANCELLED:
                await self.repository.ensure_cancelled_refund(
                    order, payment, self.clock()
                )
            await self._finish_event(event, EventStatus.IGNORED, "DUPLICATE_SUCCESS")
            return
        now = self.clock()
        attempt = await self.repository.save_attempt(
            attempt,
            transition_attempt(
                attempt, AttemptStatus.SUCCEEDED, now, verified_capture=True
            ),
        )
        if payment.status == PaymentStatus.PAID:
            if order.status == OrderStatus.CANCELLED:
                await self.repository.ensure_cancelled_refund(order, payment, now)
            if not payment.reconciliation_required:
                await self.repository.save_payment(
                    payment, replace(payment, reconciliation_required=True)
                )
            await self._finish_event(
                event,
                EventStatus.PROCESSED,
                "ADDITIONAL_CAPTURE_RECONCILIATION_REQUIRED",
            )
            return
        if payment.status == PaymentStatus.FAILED:
            payment = await self._change(
                payment,
                PaymentStatus.PROCESSING,
                now,
                source=HistorySource.PROVIDER,
                attempt=attempt,
                event_id=event.provider_event_id,
            )
        payment = await self._change(
            payment,
            PaymentStatus.PAID,
            now,
            source=HistorySource.PROVIDER,
            attempt=attempt,
            event_id=event.provider_event_id,
        )
        await self.orders.confirm_paid(order, now, online=True)
        reason = None
        if order.status == OrderStatus.CANCELLED:
            await self.repository.ensure_cancelled_refund(order, payment, now)
            reason = "PAID_AFTER_CANCELLATION_RECONCILIATION_REQUIRED"
        elif await self.repository.active_attempt(payment.id) is not None:
            reason = "OUTSTANDING_ATTEMPT_RECONCILIATION_REQUIRED"
        if reason:
            await self.repository.save_payment(
                payment, replace(payment, reconciliation_required=True)
            )
        await self._finish_event(event, EventStatus.PROCESSED, reason)
