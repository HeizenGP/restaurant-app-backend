from datetime import date
from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.orders.application.customer_records import CustomerOrderReader
from app.modules.reviews.application.ports import ReviewRepository
from app.modules.reviews.domain.models import completed_order, review_values
from app.shared.application.administration import (
    AdministrationAuthorization,
    AdministrationConflict,
    AdministrationNotFound,
    require_administration,
)
from app.shared.application.customer_identity import customer_identity
from app.shared.application.exceptions import RequestDataError
from app.shared.domain.calendar import calendar_bounds


class ReviewService:
    def __init__(
        self,
        repository: ReviewRepository,
        orders: CustomerOrderReader,
        authorization: AdministrationAuthorization,
    ):
        self.repository, self.orders, self.authorization = (
            repository,
            orders,
            authorization,
        )

    async def create(
        self, principal: Principal, order_id: UUID, rating: int, comment: str | None
    ):
        customer = customer_identity(principal)
        try:
            try:
                rating, comment = review_values(rating, comment)
            except ValueError:
                raise RequestDataError("Invalid rating or plain-text comment") from None
            order = await self.orders.customer_order(customer, order_id, lock=True)
            if order is None:
                raise AdministrationNotFound("ORDER_NOT_FOUND", "Order not found")
            if not completed_order(order.mode, order.status):
                raise AdministrationConflict(
                    "ORDER_NOT_REVIEWABLE", "Order is not completed"
                )
            if await self.repository.find_review(customer, order_id):
                raise AdministrationConflict(
                    "ORDER_ALREADY_REVIEWED", "Order already reviewed"
                )
            result = await self.repository.create_review(
                order.id, customer, order.branch_id, rating, comment
            )
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def get(self, principal: Principal, order_id: UUID):
        review = await self.repository.find_review(
            customer_identity(principal), order_id
        )
        if review is None:
            raise AdministrationNotFound("REVIEW_NOT_FOUND", "Review not found")
        return review

    async def list(
        self,
        principal: Principal,
        branch_id: UUID,
        rating: int | None,
        from_date: date | None,
        to_date: date | None,
        limit: int,
        offset: int,
    ):
        await require_administration(
            self.authorization, principal, branch_id, "REVIEW_VIEW"
        )
        scopes = await self.authorization.authorized_branches(
            principal.user_id, "REVIEW_VIEW", branch_id=branch_id
        )
        if not scopes:
            raise AdministrationNotFound("BRANCH_NOT_FOUND", "Branch not found")
        try:
            start, end = calendar_bounds(from_date, to_date, scopes[0].timezone)
        except ValueError:
            raise RequestDataError("Invalid date range") from None
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise RequestDataError("Invalid pagination")
        if rating is not None:
            try:
                review_values(rating, None)
            except ValueError:
                raise RequestDataError("Invalid rating") from None
        return await self.repository.branch_reviews(
            branch_id, rating, start, end, limit, offset
        )
