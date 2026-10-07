from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.reviews.domain.models import OrderReview


class ReviewRepository(Protocol):
    async def find_review(
        self, customer_id: UUID, order_id: UUID
    ) -> OrderReview | None: ...
    async def create_review(
        self,
        order_id: UUID,
        customer_id: UUID,
        branch_id: UUID,
        rating: int,
        comment: str | None,
    ) -> OrderReview: ...
    async def branch_reviews(
        self,
        branch_id: UUID,
        rating: int | None,
        start: datetime | None,
        end: datetime | None,
        limit: int,
        offset: int,
    ) -> list[dict]: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
