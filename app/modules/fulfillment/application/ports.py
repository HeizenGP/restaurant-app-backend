from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.fulfillment.domain.models import (
    DecisionStatus,
    DeliveryAssignment,
    DeliveryDelayIncident,
)
from app.modules.orders.domain.fulfillment import OrderFulfillmentContext
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    OrderStatus,
    StatusHistory,
)


class FulfillmentOrdersGateway(Protocol):
    async def settings_and_queue(
        self, branch_id: UUID
    ) -> tuple[BranchOrderSettings, int]: ...
    async def pickup_candidates(
        self,
        branch_id: UUID,
        limit: int,
        offset: int = 0,
        *,
        now: datetime | None = None,
        prep_minutes: int | None = None,
        lock: bool = False,
    ) -> list[OrderFulfillmentContext]: ...
    async def lock_order(
        self, branch_id: UUID, order_id: UUID
    ) -> OrderFulfillmentContext | None: ...
    async def delivery_queue(
        self, branch_id: UUID, status: OrderStatus | None, limit: int, offset: int
    ) -> list[OrderFulfillmentContext]: ...
    async def delay_candidates(
        self, branch_id: UUID, now: datetime, limit: int, after_order_number: int
    ) -> list[OrderFulfillmentContext]: ...
    async def transition(
        self, order: OrderFulfillmentContext, history: StatusHistory
    ) -> None: ...


class FulfillmentAuthorization(Protocol):
    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission: str
    ) -> bool: ...
    async def staff_is_active(
        self, user_id: UUID, branch_id: UUID, now: datetime
    ) -> bool: ...


class FulfillmentRepository(Protocol):
    async def active_assignments(
        self, order_ids: list[UUID]
    ) -> dict[UUID, DeliveryAssignment]: ...
    async def active_assignment(
        self, order_id: UUID, *, lock: bool
    ) -> DeliveryAssignment | None: ...
    async def insert_assignment(self, assignment: DeliveryAssignment) -> None: ...
    async def close_assignment(
        self, original: DeliveryAssignment, updated: DeliveryAssignment
    ) -> DeliveryAssignment: ...
    async def insert_incident(self, incident: DeliveryDelayIncident) -> bool: ...
    async def list_incidents(
        self, branch_id: UUID, status: DecisionStatus | None, limit: int, offset: int
    ) -> list[DeliveryDelayIncident]: ...
    async def lock_incident(
        self, branch_id: UUID, incident_id: UUID
    ) -> DeliveryDelayIncident | None: ...
    async def save_decision(
        self, original: DeliveryDelayIncident, updated: DeliveryDelayIncident
    ) -> DeliveryDelayIncident: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
