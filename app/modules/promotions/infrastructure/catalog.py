from app.modules.catalog.application.services import CatalogService


class CatalogPrizeGateway:
    def __init__(self, catalog: CatalogService):
        self.catalog = catalog

    async def products(self, branch_id, product_ids):
        return {
            p.id: p for p in await self.catalog.product_batch(branch_id, product_ids)
        }
