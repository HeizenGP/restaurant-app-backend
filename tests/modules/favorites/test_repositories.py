import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock
from uuid import uuid4

from app.modules.catalog.application.services import CatalogService
from app.modules.favorites.domain.models import Favorite
from app.modules.favorites.infrastructure.catalog import CatalogFavoriteGateway
from app.modules.favorites.infrastructure.persistence.repositories import (
    SQLAlchemyFavoriteRepository,
)
from app.modules.promotions.infrastructure.catalog import CatalogPrizeGateway
from tests.modules.admin.test_repositories import result
from tests.modules.extras_support import NOW, public_product


def test_idempotent_upsert_bound_user_product_and_owner_delete():
    session = AsyncMock()
    row = Favorite(uuid4(), uuid4(), uuid4(), NOW)
    session.execute.side_effect = [result(), result(mapping=asdict(row))]
    repo = SQLAlchemyFavoriteRepository(session)
    assert asyncio.run(repo.add_favorite(row.user_id, row.product_id)) == row
    calls = session.execute.await_args_list
    assert "ON CONFLICT(user_id,product_id) DO NOTHING" in str(calls[0].args[0])
    assert calls[0].args[1] == {"user": row.user_id, "product": row.product_id}
    assert "WHERE user_id=:user AND product_id=:product" in str(calls[1].args[0])
    session.execute.side_effect = None
    asyncio.run(repo.remove_favorite(row.user_id, row.product_id))
    sql, params = session.execute.await_args.args
    assert "WHERE user_id=:user AND product_id=:product" in str(sql)
    assert str(row.user_id) not in str(sql) and params["user"] == row.user_id
    session.commit.assert_not_called()


def test_favorite_list_owner_filtered_stable_pagination_bound():
    session = AsyncMock()
    session.execute.return_value = result(mappings=[])
    user = uuid4()
    asyncio.run(SQLAlchemyFavoriteRepository(session).list_favorites(user, 100, 500))
    sql, params = session.execute.await_args.args
    assert (
        "WHERE user_id=:user ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET "
        ":offset" in str(sql)
    )
    assert params == {"user": user, "limit": 100, "offset": 500}


def test_catalog_gateways_batched_own_public_projection_no_private_repository_access():
    async def verify():
        session, catalog = AsyncMock(), AsyncMock()
        product = public_product()
        catalog.product_batch.return_value = (product,)
        session.scalar.return_value = True
        branch = uuid4()
        gateway = CatalogFavoriteGateway(session, catalog)
        assert await gateway.product_exists(product.id)
        assert "SELECT EXISTS" in str(session.scalar.await_args.args[0])
        assert await gateway.products(branch, (product.id,)) == {product.id: product}
        assert await CatalogPrizeGateway(catalog).products(branch, (product.id,)) == {
            product.id: product
        }
        assert catalog.product_batch.await_count == 2
        assert catalog.product_batch.await_args.args == (branch, (product.id,))

    asyncio.run(verify())


def test_catalog_public_batch_one_query_and_active_branch_even_empty():
    async def verify():
        repo, auth, audit = AsyncMock(), AsyncMock(), AsyncMock()
        repo.branch_is_active.return_value = True
        repo.public_products.return_value = []
        service = CatalogService(repo, auth, audit)
        branch, ids = uuid4(), tuple(uuid4() for _ in range(100))
        assert await service.product_batch(branch, ids) == ()
        repo.public_products.assert_awaited_once_with(branch, product_ids=ids)
        assert await service.product_batch(branch, ()) == ()
        assert (
            repo.branch_is_active.await_count == 2
            and repo.public_products.await_count == 1
        )
        repo.branch_is_active.return_value = False
        import pytest

        from app.modules.catalog.application.errors import CatalogNotFoundError

        with pytest.raises(CatalogNotFoundError):
            await service.product_batch(branch, ())

    asyncio.run(verify())
