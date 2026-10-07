import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from app.shared.application.customer_identity import RegisteredAccountRequired
from app.shared.application.exceptions import NotFoundError, RequestDataError
from tests.modules.extras_factories import favorite_setup
from tests.modules.extras_support import principal


def test_add_delete_idempotence_and_owner_namespace():
    async def verify():
        s = favorite_setup()
        product = s.catalog.product.id
        first = await s.service.add(s.customer, product)
        second = await s.service.add(s.customer, product)
        foreign = principal()
        other = await s.service.add(foreign, product)
        assert first == second and first.id != other.id and len(s.repo.rows) == 2
        result = await s.service.list(s.customer, s.branch)
        assert [x["id"] for x in result] == [first.id]
        assert s.catalog.batches == [(s.branch, (product,))]
        await s.service.remove(s.customer, product)
        await s.service.remove(s.customer, product)
        assert list(s.repo.rows) == [(foreign.user_id, product)]

    asyncio.run(verify())


@pytest.mark.parametrize("operation", ["add", "remove", "list"])
def test_guest_cannot_use_account_favorites(operation):
    async def verify():
        s = favorite_setup()
        args = (s.branch,) if operation == "list" else (s.catalog.product.id,)
        with pytest.raises(RegisteredAccountRequired) as error:
            await getattr(s.service, operation)(principal(guest=True), *args)
        assert error.value.code == "REGISTERED_ACCOUNT_REQUIRED"
        assert not s.repo.rows and not s.catalog.batches

    asyncio.run(verify())


def test_hidden_unavailable_catalog_preserves_stored_favorite():
    async def verify():
        s = favorite_setup()
        await s.service.add(s.customer, s.catalog.product.id)
        s.catalog.product = replace(s.catalog.product, is_available=False)
        rows = await s.service.list(s.customer, s.branch)
        assert len(rows) == 1 and not rows[0]["product"].is_available
        s.catalog.hidden = True
        assert await s.service.list(s.customer, s.branch) == []
        assert len(s.repo.rows) == 1
        s.catalog.hidden = False
        assert len(await s.service.list(s.customer, s.branch)) == 1

    asyncio.run(verify())


def test_missing_product_rolls_back_with_no_favorite():
    async def verify():
        s = favorite_setup()
        with pytest.raises(NotFoundError):
            await s.service.add(s.customer, uuid4())
        assert not s.repo.rows and s.repo.rollbacks == 1 and s.repo.commits == 0

    asyncio.run(verify())


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (50, -1), (50, 10001)])
def test_pagination_bounded(limit, offset):
    async def verify():
        s = favorite_setup()
        with pytest.raises(RequestDataError):
            await s.service.list(s.customer, s.branch, limit, offset)
        assert not s.catalog.batches

    asyncio.run(verify())


def test_many_favorites_use_one_catalog_batch_even_if_not_visible():
    async def verify():
        s = favorite_setup()
        for _ in range(30):
            await s.repo.add_favorite(s.customer.user_id, uuid4())
        assert await s.service.list(s.customer, s.branch) == []
        assert len(s.catalog.batches) == 1 and len(s.catalog.batches[0][1]) == 30

    asyncio.run(verify())
