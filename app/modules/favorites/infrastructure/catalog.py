from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.services import CatalogService


class CatalogFavoriteGateway:
    def __init__(self, session: AsyncSession, catalog: CatalogService):
        self.session = session
        self.catalog = catalog

    async def product_exists(self, product_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                text("SELECT EXISTS(SELECT 1 FROM products WHERE id=:id)"),
                {"id": product_id},
            )
        )

    async def products(self, branch_id: UUID, product_ids: tuple[UUID, ...]):
        return {
            p.id: p for p in await self.catalog.product_batch(branch_id, product_ids)
        }
