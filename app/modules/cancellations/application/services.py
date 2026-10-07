from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cancellations.application.dtos import (
    CancellationOutcome,
    RequestCreation,
)
from app.modules.cancellations.application.errors import (
    CancellationConflictError,
    CancellationNotFoundError,
    CancellationPermissionDeniedError,
)
from app.modules.cancellations.application.ports import (
    CancellationAuthorization,
    CancellationFulfillmentGateway,
    CancellationOrdersGateway,
    CancellationRepository,
    RefundRegistrationGateway,
)
from app.modules.cancellations.domain.models import (
    CancellationRequest,
    CancellationRuleError,
    CancellationSource,
    OrderCancellation,
    ReasonCode,
    RequestStatus,
    plain_text,
)
from app.modules.cancellations.domain.policies import decide_request
from app.modules.orders.domain.cancellations import validate_cancellation
from app.modules.orders.domain.models import OrderRuleError, OrderStatus
from app.shared.application.audit import AuditRecord, AuditRecorder
from app.shared.application.exceptions import (
    DependencyUnavailableError,
    ForbiddenError,
    RequestDataError,
)
from app.shared.domain.time import utc_now


def pagination(limit, offset=0):
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or not 0 <= offset <= 2147483647
    ):
        raise RequestDataError("Invalid cancellation pagination")


class CancellationService:
    def __init__(
        self,
        repository: CancellationRepository,
        orders: CancellationOrdersGateway,
        authorization: CancellationAuthorization,
        refunds: RefundRegistrationGateway,
        fulfillment: CancellationFulfillmentGateway,
        audit: AuditRecorder,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.repo, self.orders, self.authorization = repository, orders, authorization
        self.refunds, self.fulfillment, self.audit, self.clock = (
            refunds,
            fulfillment,
            audit,
            clock,
        )

    async def _transaction(self, work):
        try:
            result = await work()
            await self.repo.commit()
            return result
        except (CancellationRuleError, OrderRuleError):
            await self.repo.rollback()
            raise CancellationConflictError() from None
        except Exception:
            await self.repo.rollback()
            raise

    @staticmethod
    def _customer(principal):
        if principal.customer_id is None:
            raise ForbiddenError("Customer identity required")
        return principal.customer_id

    async def _authorize(self, principal: Principal, branch: UUID, permission: str):
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
            or not await self.authorization.has_permission(
                principal.user_id, branch, permission
            )
        ):
            raise CancellationPermissionDeniedError()
        return principal.user_id

    async def _order(self, branch, order_id):
        order = await self.orders.scoped(branch, order_id, lock=True)
        if order is None:
            raise CancellationNotFoundError("ORDER_NOT_FOUND")
        return order

    async def _audit(self, actor, branch, action, kind, entity_id, after):
        await self.audit.record(
            AuditRecord(
                actor_user_id=actor,
                branch_id=branch,
                action=action,
                entity_type=kind,
                entity_id=entity_id,
                before_state=None,
                after_state=after,
            )
        )

    async def create_request(self, principal, order_id, reason):
        reason = plain_text(reason)

        async def work():
            customer = self._customer(principal)
            order = await self.orders.owned(customer, order_id, lock=True)
            if order is None:
                raise CancellationNotFoundError("ORDER_NOT_FOUND")
            validate_cancellation(order)
            old = await self.repo.pending_request(order.id)
            if old is not None:
                if old.reason != reason:
                    raise CancellationConflictError(
                        "CANCELLATION_REQUEST_ALREADY_PENDING"
                    )
                return RequestCreation(request=old, created=False)
            now = self.clock()
            request = CancellationRequest(
                order_id=order.id,
                branch_id=order.branch_id,
                customer_id=customer,
                reason=reason,
                requested_at=now,
                created_at=now,
                updated_at=now,
            )
            await self.repo.insert_request(request)
            return RequestCreation(request=request, created=True)

        return await self._transaction(work)

    async def list_owned(self, principal, order_id, limit=50, offset=0):
        pagination(limit, offset)
        customer = self._customer(principal)
        if await self.orders.owned(customer, order_id, lock=False) is None:
            raise CancellationNotFoundError("ORDER_NOT_FOUND")
        return await self.repo.list_owned(customer, order_id, limit, offset)

    async def list_branch(
        self, principal, branch, status=RequestStatus.PENDING, limit=50, offset=0
    ):
        pagination(limit, offset)
        await self._authorize(principal, branch, "CANCELLATION_VIEW")
        return await self.repo.list_branch(branch, status, limit, offset)

    async def _cancel(self, order, cancellation, actor, now):
        validate_cancellation(order)
        await self.orders.cancel(
            order,
            actor,
            now,
            "Order cancelled after approved customer request"
            if cancellation.source == CancellationSource.CUSTOMER_REQUEST
            else "Order cancelled by administrator: " + cancellation.reason_code.value,
        )
        await self.repo.insert_cancellation(cancellation)
        # Registration is local, in this same transaction; never HTTP.
        refund = await self.refunds.register_if_paid(order, now)
        await self.fulfillment.close_assignment(order.id, actor, now)
        await self._audit(
            actor,
            order.branch_id,
            "ORDER_CANCELLED",
            "order_cancellation",
            cancellation.id,
            {"order_id": str(order.id), "reason_code": cancellation.reason_code.value},
        )
        return CancellationOutcome(cancellation=cancellation, refund=refund)

    async def review(self, principal, branch, request_id, target, note=None):
        note = plain_text(note, 2000) if note is not None else None

        async def work():
            actor = await self._authorize(principal, branch, "CANCELLATION_MANAGE")
            # Scoped lookup is read-only. Lock ORDER first in EVERY mutation path,
            # then refresh/lock REQUEST; direct cancel and create use the same order.
            initial = await self.repo.request(branch, request_id, lock=False)
            if initial is None:
                raise CancellationNotFoundError()
            order = await self._order(branch, initial.order_id)
            request = await self.repo.request(branch, request_id, lock=True)
            if request is None:
                raise CancellationNotFoundError()
            if (request.order_id, request.customer_id, request.branch_id) != (
                order.id,
                order.customer_id,
                order.branch_id,
            ):
                raise DependencyUnavailableError(
                    "Cancellation evidence is inconsistent"
                )
            try:
                updated = decide_request(request, target, actor, self.clock(), note)
            except CancellationRuleError:
                raise CancellationConflictError(
                    "CANCELLATION_REQUEST_ALREADY_DECIDED"
                ) from None
            if updated == request:
                if target == RequestStatus.REJECTED:
                    return request
                cancellation = await self.repo.cancellation(order.id)
                if cancellation is None or order.status != OrderStatus.CANCELLED:
                    raise DependencyUnavailableError(
                        "Cancellation evidence is inconsistent"
                    )
                refund = await self.refunds.register_if_paid(order, self.clock())
                return CancellationOutcome(cancellation=cancellation, refund=refund)
            if target == RequestStatus.REJECTED:
                result = await self.repo.save_request(request, updated)
            else:
                cancellation = OrderCancellation(
                    order_id=order.id,
                    branch_id=branch,
                    source=CancellationSource.CUSTOMER_REQUEST,
                    reason_code=ReasonCode.CUSTOMER_REQUEST,
                    cancellation_request_id=request.id,
                    reason_text=request.reason,
                    cancelled_by_user_id=actor,
                    cancelled_at=self.clock(),
                    created_at=self.clock(),
                )
                result = await self._cancel(order, cancellation, actor, self.clock())
                await self.repo.save_request(request, updated)
            await self._audit(
                actor,
                branch,
                "CANCELLATION_REQUEST_" + target.value,
                "cancellation_request",
                request.id,
                {"status": target.value},
            )
            return result

        return await self._transaction(work)

    async def cancel_order(self, principal, branch, order_id, reason_code, reason=None):
        reason = plain_text(reason) if reason is not None else None

        async def work():
            actor = await self._authorize(principal, branch, "CANCELLATION_MANAGE")
            order = await self._order(branch, order_id)
            existing = await self.repo.cancellation(order.id)
            if order.status == OrderStatus.CANCELLED:
                if existing is not None and (
                    existing.source,
                    existing.reason_code,
                    existing.reason_text,
                    existing.cancelled_by_user_id,
                ) == (CancellationSource.ADMIN, reason_code, reason, actor):
                    return CancellationOutcome(
                        cancellation=existing,
                        refund=await self.refunds.register_if_paid(order, self.clock()),
                    )
                raise CancellationConflictError("ORDER_ALREADY_CANCELLED")
            if existing is not None:
                raise DependencyUnavailableError(
                    "Cancellation evidence is inconsistent"
                )
            now = self.clock()
            cancellation = OrderCancellation(
                order_id=order.id,
                branch_id=branch,
                source=CancellationSource.ADMIN,
                reason_code=reason_code,
                reason_text=reason,
                cancelled_by_user_id=actor,
                cancelled_at=now,
                created_at=now,
            )
            pending = await self.repo.pending_request(order.id)
            result = await self._cancel(order, cancellation, actor, now)
            if pending is not None:
                updated = decide_request(
                    pending,
                    RequestStatus.APPROVED,
                    actor,
                    now,
                    "Resolved by direct administrative cancellation",
                )
                await self.repo.save_request(pending, updated)
                await self._audit(
                    actor,
                    branch,
                    "CANCELLATION_REQUEST_APPROVED",
                    "cancellation_request",
                    pending.id,
                    {"status": "APPROVED"},
                )
            return result

        return await self._transaction(work)

    async def detail(self, principal, branch, order_id):
        await self._authorize(principal, branch, "CANCELLATION_VIEW")
        if await self.orders.scoped(branch, order_id, lock=False) is None:
            raise CancellationNotFoundError("ORDER_NOT_FOUND")
        cancellation = await self.repo.cancellation(order_id)
        if cancellation is None:
            raise CancellationNotFoundError("ORDER_CANCELLATION_NOT_FOUND")
        return CancellationOutcome(
            cancellation=cancellation, refund=await self.refunds.for_order(order_id)
        )
