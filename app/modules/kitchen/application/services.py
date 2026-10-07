from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.kitchen.application.dtos import (
    KitchenOrder,
    KitchenQueue,
    KitchenQueueQuery,
    group_queue,
    kitchen_order,
)
from app.modules.kitchen.application.errors import (
    KitchenIntegrityError,
    KitchenInvalidTransitionError,
    KitchenOrderNotConfirmedError,
    KitchenOrderNotFoundError,
    KitchenPermissionDeniedError,
)
from app.modules.kitchen.application.ports import (
    KitchenAuthorization,
    KitchenOrdersGateway,
)
from app.modules.kitchen.domain.models import KitchenDataError, target_ready_status
from app.modules.orders.domain.models import (
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)
from app.modules.orders.domain.transitions import validate_transition
from app.shared.domain.time import utc_now


class KitchenService:
    def __init__(
        self,
        orders: KitchenOrdersGateway,
        authorization: KitchenAuthorization,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._orders = orders
        self._authorization = authorization
        self._clock = clock

    async def _authorize(
        self, principal: Principal, branch_id: UUID, permission: str
    ) -> None:
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
            or not await self._authorization.has_permission(
                principal.user_id, branch_id, permission
            )
        ):
            raise KitchenPermissionDeniedError()

    async def get_queue(
        self, principal: Principal, branch_id: UUID, query: KitchenQueueQuery
    ) -> KitchenQueue:
        await self._authorize(principal, branch_id, "KITCHEN_VIEW")
        try:
            snapshots = await self._orders.queue(branch_id, query)
            return group_queue(snapshots, self._clock(), query)
        except KitchenDataError:
            raise KitchenIntegrityError() from None

    async def get_kitchen_order(
        self, principal: Principal, branch_id: UUID, order_id: UUID
    ) -> KitchenOrder:
        await self._authorize(principal, branch_id, "KITCHEN_VIEW")
        try:
            snapshot = await self._orders.get_order(branch_id, order_id)
            if snapshot is None:
                raise KitchenOrderNotFoundError()
            return kitchen_order(snapshot, self._clock())
        except KitchenDataError:
            raise KitchenIntegrityError() from None

    async def start_preparation(
        self, principal: Principal, branch_id: UUID, order_id: UUID
    ) -> KitchenOrder:
        return await self._prepare(principal, branch_id, order_id, ready=False)

    async def mark_ready(
        self, principal: Principal, branch_id: UUID, order_id: UUID
    ) -> KitchenOrder:
        return await self._prepare(principal, branch_id, order_id, ready=True)

    async def _prepare(
        self, principal: Principal, branch_id: UUID, order_id: UUID, *, ready: bool
    ) -> KitchenOrder:
        try:
            await self._authorize(principal, branch_id, "KITCHEN_MANAGE")
            order = await self._orders.lock_order(branch_id, order_id)
            if order is None:
                raise KitchenOrderNotFoundError()
            if order.confirmed_at is None or (
                order.payment_method_type == PaymentMethodType.ONLINE
                and order.payment_status != PaymentStatus.PAID
            ):
                raise KitchenOrderNotConfirmedError()
            target = target_ready_status(order.mode) if ready else OrderStatus.PREPARING
            source = OrderStatus.PREPARING if ready else OrderStatus.WAITING
            now = self._clock()
            if order.status != target:
                if order.status != source:
                    raise KitchenInvalidTransitionError()
                validate_transition(order, target)
                # Check the current history before writing, including retries.
                before = await self._orders.get_order(branch_id, order_id)
                if before is None:
                    raise KitchenIntegrityError()
                kitchen_order(before, now)
                history = StatusHistory(
                    from_status=order.status,
                    to_status=target,
                    changed_by_user_id=principal.user_id,
                    reason="Kitchen marked order ready"
                    if ready
                    else "Kitchen started preparation",
                    created_at=now,
                )
                await self._orders.record_preparation_transition(order, history)
            snapshot = await self._orders.get_order(branch_id, order_id)
            if snapshot is None:
                raise KitchenIntegrityError()
            result = kitchen_order(snapshot, now)
            await self._orders.commit()
            return result
        except OrderRuleError:
            await self._orders.rollback()
            raise KitchenInvalidTransitionError() from None
        except KitchenDataError:
            await self._orders.rollback()
            raise KitchenIntegrityError() from None
        except Exception:
            await self._orders.rollback()
            raise
