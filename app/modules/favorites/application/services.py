from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.favorites.application.ports import FavoriteCatalog, FavoriteRepository
from app.shared.application.administration import AdministrationNotFound
from app.shared.application.customer_identity import account_identity
from app.shared.application.exceptions import RequestDataError


class FavoriteService:
    def __init__(self, repository: FavoriteRepository, catalog: FavoriteCatalog):
        self.repository = repository
        self.catalog = catalog

    async def list(
        self, principal: Principal, branch_id: UUID, limit: int = 50, offset: int = 0
    ):
        user = account_identity(principal)
        if not 1 <= limit <= 100 or not 0 <= offset <= 10000:
            raise RequestDataError("Invalid pagination")
        favorites = await self.repository.list_favorites(user, limit, offset)
        products = await self.catalog.products(
            branch_id, tuple(f.product_id for f in favorites)
        )
        return [
            {
                "id": f.id,
                "product_id": f.product_id,
                "created_at": f.created_at,
                "product": products[f.product_id],
            }
            for f in favorites
            if f.product_id in products
        ]

    async def add(self, principal: Principal, product_id: UUID):
        user = account_identity(principal)
        try:
            if not await self.catalog.product_exists(product_id):
                raise AdministrationNotFound(
                    "FAVORITE_PRODUCT_NOT_FOUND", "Product not found"
                )
            result = await self.repository.add_favorite(user, product_id)
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def remove(self, principal: Principal, product_id: UUID):
        user = account_identity(principal)
        try:
            await self.repository.remove_favorite(user, product_id)
            await self.repository.commit()
        except Exception:
            await self.repository.rollback()
            raise
