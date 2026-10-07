from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reviews.domain.models import OrderReview
from app.shared.application.administration import AdministrationConflict


class SQLAlchemyReviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_review(self, customer_id, order_id):
        row = await self.session.execute(
            text(
                "SELECT * FROM order_reviews WHERE order_id=:order AND "
                "customer_id=:customer"
            ),
            {"order": order_id, "customer": customer_id},
        )
        found = row.mappings().one_or_none()
        return OrderReview(**found) if found else None

    async def create_review(self, order_id, customer_id, branch_id, rating, comment):
        try:
            row = await self.session.execute(
                text(
                    "INSERT INTO order_reviews(order_id,customer_id,branch_id,"
                    "rating,comment) "
                    "VALUES (:order,:customer,:branch,:rating,:comment) RETURNING *"
                ),
                {
                    "order": order_id,
                    "customer": customer_id,
                    "branch": branch_id,
                    "rating": rating,
                    "comment": comment,
                },
            )
        except IntegrityError:
            raise AdministrationConflict(
                "ORDER_ALREADY_REVIEWED", "Order already reviewed"
            ) from None
        return OrderReview(**row.mappings().one())

    async def branch_reviews(self, branch_id, rating, start, end, limit, offset):
        row = await self.session.execute(
            text(
                "SELECT r.id,r.order_id,o.order_number,r.rating,r.comment,r.created_at "
                "FROM order_reviews r JOIN orders o ON o.id=r.order_id WHERE "
                "r.branch_id=:branch "
                "AND (CAST(:rating AS smallint) IS NULL OR r.rating=:rating) "
                "AND (CAST(:start AS timestamptz) IS NULL OR r.created_at>=:start) "
                "AND (CAST(:end AS timestamptz) IS NULL OR r.created_at<:end) "
                "ORDER BY r.created_at DESC,r.id DESC LIMIT :limit OFFSET :offset"
            ),
            {
                "branch": branch_id,
                "rating": rating,
                "start": start,
                "end": end,
                "limit": limit,
                "offset": offset,
            },
        )
        return [dict(r) for r in row.mappings()]

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
