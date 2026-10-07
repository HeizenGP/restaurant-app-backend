import asyncio
from dataclasses import asdict
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.orders.infrastructure.customer_records import (
    SQLAlchemyCustomerOrderReader,
)
from app.modules.reviews.infrastructure.persistence.repositories import (
    SQLAlchemyReviewRepository,
)
from app.shared.application.exceptions import ConflictError
from tests.modules.admin.test_repositories import result
from tests.modules.extras_factories import review_setup
from tests.modules.extras_support import NOW


def test_owner_read_and_order_gateway_do_not_expose_pii_or_write_lifecycle():
    session = AsyncMock()
    s = review_setup()
    session.execute.return_value = result(mapping=asdict(s.orders.order))
    reader = SQLAlchemyCustomerOrderReader(session)
    assert (
        asyncio.run(
            reader.customer_order(s.customer.customer_id, s.orders.order.id, lock=True)
        )
        == s.orders.order
    )
    sql, params = session.execute.await_args.args
    assert "o.customer_id=:customer" in str(sql) and "FOR UPDATE OF o" in str(sql)
    assert "LEFT JOIN payments" in str(sql)
    assert params["customer"] == s.customer.customer_id
    assert all(
        word not in str(sql)
        for word in ("password", "phone", "UPDATE orders", "INSERT")
    )
    session.execute.return_value = result()
    asyncio.run(
        SQLAlchemyReviewRepository(session).find_review(
            s.customer.customer_id, s.orders.order.id
        )
    )
    assert "customer_id=:customer" in str(session.execute.await_args.args[0])


def test_scoped_admin_projection_and_typed_filters_before_pagination():
    session = AsyncMock()
    session.execute.return_value = result(mappings=[])
    branch = uuid4()
    asyncio.run(
        SQLAlchemyReviewRepository(session).branch_reviews(branch, 5, NOW, NOW, 50, 20)
    )
    sql, params = session.execute.await_args.args
    sql = str(sql)
    assert sql.index("r.branch_id=:branch") < sql.index("LIMIT :limit")
    assert (
        "ORDER BY r.created_at DESC,r.id DESC" in sql
        and "CAST(:rating AS smallint)" in sql
    )
    assert "r.id,r.order_id,o.order_number,r.rating,r.comment,r.created_at" in sql
    assert not any(x in sql for x in ("c.phone", "users", "SELECT *"))
    assert params == {
        "branch": branch,
        "rating": 5,
        "start": NOW,
        "end": NOW,
        "limit": 50,
        "offset": 20,
    }


def test_unique_violation_maps_safe_409_no_sql_details():
    session = AsyncMock()
    session.execute.side_effect = IntegrityError(
        "private-query", {}, Exception("private-pii")
    )
    with pytest.raises(ConflictError) as error:
        asyncio.run(
            SQLAlchemyReviewRepository(session).create_review(
                uuid4(), uuid4(), uuid4(), 5, None
            )
        )
    assert error.value.code == "ORDER_ALREADY_REVIEWED" and "private" not in str(
        error.value
    )
