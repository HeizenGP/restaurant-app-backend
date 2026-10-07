"""Refund orchestration. Original Payment/Order are never changed here."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.orders.domain.models import PaymentMethodType
from app.modules.payments.application.refund_dtos import (
    RefundAttemptRequest,
    RefundProcessing,
)
from app.modules.payments.application.refund_errors import (
    RefundConflictError,
    RefundDataError,
    RefundEventPendingError,
    RefundNotFoundError,
    RefundPermissionDeniedError,
    RefundProviderUnavailableError,
    RefundWebhookAuthenticationError,
)
from app.modules.payments.application.refund_ports import (
    OnlineRefundGateway,
    RefundAuthorization,
    RefundRepository,
)
from app.modules.payments.domain.models import (
    AttemptStatus,
    EventStatus,
    PaymentRuleError,
    VerifiedResult,
    idempotency_key,
)
from app.modules.payments.domain.refunds import (
    RefundAttempt,
    RefundHistorySource,
    RefundProviderEvent,
    RefundStatus,
    RefundStatusHistory,
    transition_refund,
    transition_refund_attempt,
)
from app.shared.application.audit import AuditRecord, AuditRecorder
from app.shared.application.exceptions import ForbiddenError, RequestDataError
from app.shared.domain.time import utc_now

MAX_REFUND_WEBHOOK_BYTES = 65536


class RefundService:
    def __init__(
        self,
        repository: RefundRepository,
        authorization: RefundAuthorization,
        gateway: OnlineRefundGateway,
        audit: AuditRecorder,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.repo, self.authorization, self.gateway, self.audit, self.clock = (
            repository,
            authorization,
            gateway,
            audit,
            clock,
        )

    async def _authorize(self, principal: Principal, branch: UUID):
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
            or not await self.authorization.has_permission(
                principal.user_id, branch, "REFUND_MANAGE"
            )
        ):
            raise RefundPermissionDeniedError()
        return principal.user_id

    async def _scoped(self, branch, refund_id, *, lock):
        refund = await self.repo.scoped(branch, refund_id, lock=lock)
        if refund is None:
            raise RefundNotFoundError()
        return refund

    async def _transaction(self, work):
        try:
            result = await work()
            await self.repo.commit()
            return result
        except PaymentRuleError:
            await self.repo.rollback()
            raise RefundConflictError() from None
        except Exception:
            await self.repo.rollback()
            raise

    async def _audit(self, actor, branch, action, refund):
        await self.audit.record(
            AuditRecord(
                actor_user_id=actor,
                branch_id=branch,
                action=action,
                entity_type="refund",
                entity_id=refund.id,
                before_state=None,
                after_state={"order_id": str(refund.order_id)},
            )
        )

    async def _change(
        self, refund, target, source, now, *, actor=None, attempt=None, event=None
    ):
        updated = await self.repo.save_refund(
            refund, transition_refund(refund, target, now)
        )
        await self.repo.append_history(
            RefundStatusHistory(
                refund_id=refund.id,
                from_status=refund.status,
                to_status=target,
                source=source,
                changed_by_user_id=actor,
                refund_attempt_id=attempt.id if attempt else None,
                provider_event_id=event,
                reason="Refund financial state confirmed",
                created_at=now,
            )
        )
        return updated

    async def get_owned(self, principal, order_id):
        if principal.customer_id is None:
            raise ForbiddenError("Customer identity required")
        refund = await self.repo.owned(principal.customer_id, order_id)
        if refund is None:
            raise RefundNotFoundError()
        return refund

    async def list_branch(
        self, principal, branch, status=None, method=None, limit=50, offset=0
    ):
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(offset) is not int
            or not 0 <= offset <= 2147483647
        ):
            raise RequestDataError("Invalid refund pagination")
        await self._authorize(principal, branch)
        return await self.repo.list_branch(branch, status, method, limit, offset)

    async def detail(self, principal, branch, refund_id):
        await self._authorize(principal, branch)
        return await self.repo.view(await self._scoped(branch, refund_id, lock=False))

    async def confirm_cash(self, principal, branch, refund_id):
        async def work():
            actor = await self._authorize(principal, branch)
            refund = await self._scoped(branch, refund_id, lock=True)
            if refund.method_type != PaymentMethodType.CASH:
                raise RefundConflictError("REFUND_METHOD_INVALID")
            if refund.status == RefundStatus.REFUNDED:
                return refund
            if refund.status != RefundStatus.PENDING:
                raise RefundConflictError()
            refund = await self._change(
                refund,
                RefundStatus.REFUNDED,
                RefundHistorySource.STAFF,
                self.clock(),
                actor=actor,
            )
            await self._audit(actor, branch, "REFUND_CASH_CONFIRMED", refund)
            return refund

        return await self._transaction(work)

    async def _reserve(self, principal, branch, refund_id, key):
        actor = await self._authorize(principal, branch)
        refund = await self._scoped(branch, refund_id, lock=True)
        if refund.method_type != PaymentMethodType.ONLINE:
            raise RefundConflictError("REFUND_METHOD_INVALID")
        attempt = await self.repo.attempt_by_key(refund.id, key)
        if attempt is not None and attempt.status != AttemptStatus.CREATED:
            return RefundProcessing(refund=refund, attempt=attempt)
        if refund.status == RefundStatus.REFUNDED:
            raise RefundConflictError("REFUND_ALREADY_COMPLETED")
        active = await self.repo.active_attempt(refund.id)
        if active is not None and (attempt is None or attempt.id != active.id):
            raise RefundConflictError("REFUND_IDEMPOTENCY_CONFLICT")
        # Resolve unconfigured gateway only after scope, before any new writes.
        provider = self.gateway.provider_code
        capture = await self.repo.successful_capture(refund.payment_id)
        if (
            capture is None
            or capture.amount != refund.amount
            or capture.provider_code != provider
        ):
            raise RefundDataError()
        if attempt is None:
            if refund.status not in {RefundStatus.PENDING, RefundStatus.FAILED}:
                raise RefundConflictError()
            now = self.clock()
            attempt = RefundAttempt(
                refund_id=refund.id,
                amount=refund.amount,
                idempotency_key=key,
                provider_code=provider,
                created_at=now,
                updated_at=now,
            )
            await self.repo.insert_attempt(attempt)
            refund = await self._change(
                refund,
                RefundStatus.PROCESSING,
                RefundHistorySource.STAFF,
                now,
                actor=actor,
                attempt=attempt,
            )
            await self._audit(actor, branch, "REFUND_ONLINE_PROCESS_REQUESTED", refund)
        elif (
            attempt.provider_code != provider
            or refund.status != RefundStatus.PROCESSING
        ):
            raise RefundConflictError()
        return refund, attempt, capture.provider_reference

    async def process_online(self, principal, branch, refund_id, key):
        try:
            idempotency_key(key)
        except PaymentRuleError:
            raise RequestDataError("Invalid refund idempotency key") from None
        reserved = await self._transaction(
            lambda: self._reserve(principal, branch, refund_id, key)
        )
        if isinstance(reserved, RefundProcessing):
            return reserved
        refund, attempt, original_reference = reserved
        # Reservation committed; no DB locks/transaction across the provider call.
        try:
            result = await self.gateway.refund(
                RefundAttemptRequest(
                    refund_id=refund.id,
                    payment_id=refund.payment_id,
                    attempt_id=attempt.id,
                    amount=refund.amount,
                    currency_code=refund.currency_code,
                    original_provider_reference=original_reference,
                    provider_idempotency_key="refund-attempt:" + str(attempt.id),
                )
            )
            if result.provider_code != attempt.provider_code:
                raise RefundProviderUnavailableError()
        except (OSError, TimeoutError, PaymentRuleError):
            raise RefundProviderUnavailableError() from None

        async def work():
            current = await self._scoped(branch, refund_id, lock=True)
            latest = await self.repo.attempt_by_id(refund_id, attempt.id, lock=True)
            if latest is None or latest.amount != current.amount:
                raise RefundDataError()
            if (
                latest.provider_reference is not None
                and result.provider_reference != latest.provider_reference
            ):
                raise RefundConflictError("REFUND_IDEMPOTENCY_CONFLICT")
            if latest.status == AttemptStatus.CREATED:
                latest = await self.repo.save_attempt(
                    latest,
                    transition_refund_attempt(
                        latest,
                        result.status,
                        self.clock(),
                        verified=result.status == AttemptStatus.SUCCEEDED,
                        reference=result.provider_reference,
                        failure="REFUND_DECLINED"
                        if result.status == AttemptStatus.FAILED
                        else None,
                    ),
                )
                if result.status == AttemptStatus.SUCCEEDED:
                    current = await self._success_state(current, latest, None)
                elif (
                    result.status == AttemptStatus.FAILED
                    and current.status == RefundStatus.PROCESSING
                ):
                    current = await self._change(
                        current,
                        RefundStatus.FAILED,
                        RefundHistorySource.PROVIDER,
                        self.clock(),
                        attempt=latest,
                    )
            return RefundProcessing(refund=current, attempt=latest)

        return await self._transaction(work)

    async def _success_state(self, refund, attempt, event_id):
        if refund.status == RefundStatus.REFUNDED:
            if not refund.reconciliation_required:
                refund = await self.repo.save_refund(
                    refund, replace(refund, reconciliation_required=True)
                )
            return refund
        now = self.clock()
        if refund.status == RefundStatus.FAILED:
            refund = await self._change(
                refund,
                RefundStatus.PROCESSING,
                RefundHistorySource.PROVIDER,
                now,
                attempt=attempt,
                event=event_id,
            )
        if refund.status != RefundStatus.PROCESSING:
            raise RefundDataError()
        refund = await self._change(
            refund,
            RefundStatus.REFUNDED,
            RefundHistorySource.PROVIDER,
            now,
            attempt=attempt,
            event=event_id,
        )
        if await self.repo.active_attempt(refund.id) is not None:
            refund = await self.repo.save_refund(
                refund, replace(refund, reconciliation_required=True)
            )
        return refund

    async def _finish_event(self, event, status, reason=None):
        await self.repo.save_event(
            event,
            replace(
                event,
                processing_status=status,
                processed_at=self.clock(),
                reason_code=reason,
            ),
        )

    async def webhook(self, provider, raw_body: bytes, headers: Mapping[str, str]):
        if len(raw_body) > MAX_REFUND_WEBHOOK_BYTES:
            raise RequestDataError("Refund webhook payload is too large")
        try:
            verified = await self.gateway.verify_and_parse_webhook(
                provider, raw_body, headers
            )
        except PaymentRuleError:
            raise RefundWebhookAuthenticationError() from None
        except (OSError, TimeoutError):
            raise RefundProviderUnavailableError() from None
        if verified.provider_code != provider:
            raise RefundWebhookAuthenticationError()
        incoming = RefundProviderEvent(
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

        async def work():
            event = await self.repo.get_or_insert_event(incoming)
            if event.payload_hash != incoming.payload_hash:
                raise RefundConflictError("REFUND_PROVIDER_EVENT_INVALID")
            if event.processing_status != EventStatus.RECEIVED and not (
                event.processing_status == EventStatus.REJECTED
                and event.reason_code == "UNKNOWN_REFERENCE"
            ):
                return False
            locator = await self.repo.attempt_locator(
                provider, event.provider_reference
            )
            if locator is None:
                await self._finish_event(
                    event, EventStatus.REJECTED, "UNKNOWN_REFERENCE"
                )
                return True
            refund = await self.repo.lock_refund(locator.refund_id)
            attempt = await self.repo.attempt_by_id(
                locator.refund_id, locator.attempt_id, lock=True
            )
            if (
                refund is None
                or attempt is None
                or refund.method_type != PaymentMethodType.ONLINE
                or attempt.provider_code != provider
                or attempt.provider_reference != event.provider_reference
                or attempt.refund_id != refund.id
            ):
                raise RefundDataError()
            event = replace(event, refund_attempt_id=attempt.id)
            if (
                event.reported_amount != attempt.amount
                or attempt.amount != refund.amount
            ):
                await self._finish_event(event, EventStatus.REJECTED, "AMOUNT_MISMATCH")
            elif event.reported_currency != refund.currency_code:
                await self._finish_event(
                    event, EventStatus.REJECTED, "CURRENCY_MISMATCH"
                )
            elif event.result == VerifiedResult.FAILED:
                if refund.status == RefundStatus.REFUNDED or attempt.status in {
                    AttemptStatus.SUCCEEDED,
                    AttemptStatus.FAILED,
                }:
                    await self._finish_event(
                        event, EventStatus.IGNORED, "STALE_FAILURE"
                    )
                else:
                    attempt = await self.repo.save_attempt(
                        attempt,
                        transition_refund_attempt(
                            attempt,
                            AttemptStatus.FAILED,
                            self.clock(),
                            failure="REFUND_DECLINED",
                        ),
                    )
                    if refund.status == RefundStatus.PROCESSING:
                        await self._change(
                            refund,
                            RefundStatus.FAILED,
                            RefundHistorySource.PROVIDER,
                            self.clock(),
                            attempt=attempt,
                            event=event.provider_event_id,
                        )
                    await self._finish_event(event, EventStatus.PROCESSED)
            elif attempt.status == AttemptStatus.SUCCEEDED:
                if refund.status != RefundStatus.REFUNDED:
                    raise RefundDataError()
                await self._finish_event(
                    event, EventStatus.IGNORED, "DUPLICATE_SUCCESS"
                )
            else:
                attempt = await self.repo.save_attempt(
                    attempt,
                    transition_refund_attempt(
                        attempt, AttemptStatus.SUCCEEDED, self.clock(), verified=True
                    ),
                )
                await self._success_state(refund, attempt, event.provider_event_id)
                await self._finish_event(event, EventStatus.PROCESSED)
            return False

        pending = await self._transaction(work)
        if pending:
            raise RefundEventPendingError()
