from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.favorites.domain.models import Favorite


class SQLAlchemyFavoriteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_favorites(self, user_id: UUID, limit: int, offset: int):
        rows = await self.session.execute(
            text(
                "SELECT id,user_id,product_id,created_at FROM customer_favorites "
                "WHERE user_id=:user ORDER BY created_at DESC,id DESC LIMIT "
                ":limit OFFSET :offset"
            ),
            {"user": user_id, "limit": limit, "offset": offset},
        )
        return [Favorite(**r) for r in rows.mappings()]

    async def add_favorite(self, user_id: UUID, product_id: UUID):
        await self.session.execute(
            text(
                "INSERT INTO customer_favorites(user_id,product_id) VALUES "
                "(:user,:product) "
                "ON CONFLICT(user_id,product_id) DO NOTHING"
            ),
            {"user": user_id, "product": product_id},
        )
        row = await self.session.execute(
            text(
                "SELECT id,user_id,product_id,created_at FROM customer_favorites "
                "WHERE user_id=:user AND product_id=:product"
            ),
            {"user": user_id, "product": product_id},
        )
        return Favorite(**row.mappings().one())

    async def remove_favorite(self, user_id: UUID, product_id: UUID):
        await self.session.execute(
            text(
                "DELETE FROM customer_favorites WHERE user_id=:user AND "
                "product_id=:product"
            ),
            {"user": user_id, "product": product_id},
        )

    async def commit(self):
        await self.session.commit()

    async def rollback(self):
        await self.session.rollback()
