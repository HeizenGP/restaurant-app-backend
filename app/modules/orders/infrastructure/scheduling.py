from uuid import UUID

from app.modules.orders.application.dtos import PreparationEstimate
from app.modules.orders.domain.models import BranchOrderSettings
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderRepository,
)


class SQLAlchemyKitchenLoadEstimator:
    """Deterministic initial estimate; no Kitchen, provider or hidden heuristic."""

    def __init__(self, repository: SQLAlchemyOrderRepository) -> None:
        self._repository = repository

    async def estimate(
        self, branch_id: UUID, settings: BranchOrderSettings
    ) -> PreparationEstimate:
        depth = await self._repository.queue_depth(branch_id)
        return PreparationEstimate(
            queue_depth=depth,
            base_prep_minutes=settings.default_prep_minutes,
            queue_delay_minutes=depth * settings.queue_delay_per_order_minutes,
        )
