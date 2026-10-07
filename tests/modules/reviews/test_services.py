import asyncio
from dataclasses import replace
from datetime import date
from itertools import product
from uuid import uuid4

import pytest

from app.modules.reviews.domain.models import completed_order, review_values
from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
)
from tests.modules.extras_factories import review_setup
from tests.modules.extras_support import principal

MODES = ("LOCAL", "PICKUP", "DELIVERY")
STATUSES = (
    "PENDING_PAYMENT",
    "PENDING_CASH_CONFIRMATION",
    "SCHEDULED",
    "WAITING",
    "PREPARING",
    "READY",
    "READY_FOR_PICKUP",
    "OUT_FOR_DELIVERY",
    "SERVED",
    "PICKED_UP",
    "DELIVERED",
    "CANCELLED",
)
TERMINAL = {"LOCAL": "SERVED", "PICKUP": "PICKED_UP", "DELIVERY": "DELIVERED"}


@pytest.mark.parametrize("mode,status", list(product(MODES, STATUSES)))
def test_exact_completed_modalities(mode, status):
    async def verify():
        s = review_setup()
        s.orders.order = replace(s.orders.order, mode=mode, status=status)
        allowed = TERMINAL[mode] == status
        assert completed_order(mode, status) == allowed
        if allowed:
            row = await s.service.create(s.customer, s.orders.order.id, 5, " Thanks ")
            assert row.comment == "Thanks" and row.branch_id == s.branch
            assert s.orders.locks == [True]
        else:
            with pytest.raises(ConflictError) as error:
                await s.service.create(s.customer, s.orders.order.id, 5, None)
            assert error.value.code == "ORDER_NOT_REVIEWABLE" and not s.repo.rows

    asyncio.run(verify())


@pytest.mark.parametrize("guest", [False, True])
def test_ownership_guest_or_registered_and_immutable_duplicate(guest):
    async def verify():
        s = review_setup(customer=principal(guest=guest))
        order = s.orders.order.id
        with pytest.raises(NotFoundError):
            await s.service.create(principal(guest=guest), order, 5, None)
        row = await s.service.create(s.customer, order, 4, "Original")
        assert await s.service.get(s.customer, order) == row
        with pytest.raises(NotFoundError):
            await s.service.get(principal(), order)
        with pytest.raises(ConflictError) as error:
            await s.service.create(s.customer, order, 1, "Changed")
        assert (
            error.value.code == "ORDER_ALREADY_REVIEWED" and s.repo.rows[order] == row
        )

    asyncio.run(verify())


@pytest.mark.parametrize("rating", [0, 6, -1, True, False, 1.0, "5", None])
def test_rating_integer_only(rating):
    with pytest.raises(ValueError):
        review_values(rating, None)


@pytest.mark.parametrize(
    "comment", ["<script>x</script>", "x>y", "x\x00y", "x" * 1001, 42]
)
def test_unsafe_comment_rejected(comment):
    async def verify():
        s = review_setup()
        with pytest.raises(RequestDataError):
            await s.service.create(s.customer, s.orders.order.id, 5, comment)
        assert not s.repo.rows

    asyncio.run(verify())


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("comment", [None, " ", "Plain\ntext\tallowed", "ñ" * 1000])
def test_review_valid_boundaries(rating, comment):
    value, text = review_values(rating, comment)
    assert value == rating and text == (
        comment.strip() or None if comment is not None else None
    )


def test_admin_branch_filters_and_long_local_calendar_period_no_pii():
    async def verify():
        s = review_setup()
        await s.service.create(s.customer, s.orders.order.id, 5, "Good")
        rows = await s.service.list(
            s.admin, s.branch, 5, date(2026, 1, 1), date(2026, 12, 31), 50, 0
        )
        assert len(rows) == 1 and s.repo.scope == [s.branch]
        assert not {"customer_id", "phone", "email"} & rows[0].keys()
        assert await s.service.list(s.admin, s.branch, 4, None, None, 50, 0) == []
        with pytest.raises(ForbiddenError):
            await s.service.list(s.admin, uuid4(), None, None, None, 50, 0)
        s.authorization.enabled = False
        with pytest.raises(ForbiddenError):
            await s.service.list(s.admin, s.branch, None, None, None, 50, 0)

    asyncio.run(verify())


@pytest.mark.parametrize(
    "args",
    [
        (None, date(2026, 10, 8), date(2026, 10, 7), 50, 0),
        (None, None, None, 101, 0),
        (None, None, None, 50, -1),
        (0, None, None, 50, 0),
    ],
)
def test_invalid_admin_filters(args):
    async def verify():
        s = review_setup()
        with pytest.raises(RequestDataError):
            await s.service.list(s.admin, s.branch, *args)
        assert not s.repo.scope

    asyncio.run(verify())
