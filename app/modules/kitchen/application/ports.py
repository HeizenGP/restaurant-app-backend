from typing import Protocol
from uuid import UUID

from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.kitchen.domain.models import KitchenOrderSnapshot
from app.modules.orders.domain.lifecycle import OrderTransitionContext
from app.modules.orders.domain.models import StatusHistory


class KitchenAuthorization(Protocol):
    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission: str
    ) -> bool: ...


class KitchenOrdersGateway(Protocol):
    async def queue(
        self, branch_id: UUID, query: KitchenQueueQuery
    ) -> list[KitchenOrderSnapshot]: ...
    async def get_order(
        self, branch_id: UUID, order_id: UUID
    ) -> KitchenOrderSnapshot | None: ...
    async def lock_order(
        self, branch_id: UUID, order_id: UUID
    ) -> OrderTransitionContext | None: ...
    async def record_preparation_transition(
        self, order: OrderTransitionContext, history: StatusHistory
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
