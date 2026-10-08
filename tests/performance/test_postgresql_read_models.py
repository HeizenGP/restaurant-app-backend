"""Synthetic TEST-only workload, real statement counts and EXPLAIN; no SLA gate."""

import asyncio
import json
from time import perf_counter

import pytest
from sqlalchemy import event, text

from app.modules.admin.domain.periods import branch_period
from app.modules.admin.infrastructure.read_repository import (
    SQLAlchemyAdministrationReadRepository,
    dashboard_statement,
)
from app.modules.cart.application.dtos import ItemCreate
from app.modules.cart.infrastructure.persistence.repositories import (
    SQLAlchemyCartRepository,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.modules.favorites.application.services import FavoriteService
from app.modules.favorites.infrastructure.catalog import CatalogFavoriteGateway
from app.modules.favorites.infrastructure.persistence.repositories import (
    SQLAlchemyFavoriteRepository,
)
from app.modules.kitchen.application.dtos import KitchenQueueQuery
from app.modules.notifications.infrastructure.persistence.repositories import (
    SQLAlchemyNotificationRepository,
)
from app.modules.orders.application.dtos import OrderCreate
from app.modules.orders.domain.models import OrderMode, PaymentMethodType
from app.shared.domain.time import utc_now
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.phase12_support import (
    checkout,
    fresh_database,
    owner,
    pay,
    seed,
    services,
    staff,
)

pytestmark = [pytest.mark.integration, pytest.mark.performance]


def test_representative_postgresql_dataset_query_budgets_and_plans(request):
    url = guarded_test_url(request)

    async def scenario():
        async with fresh_database(url) as (engine, factory):
            ids = await seed(factory)
            async with factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO products(category_id,name,slug,base_price) "
                        "SELECT :category,'TEST Product '||i,'phase12-perf-'||i,20 "
                        "FROM generate_series(1,249) i"
                    ),
                    ids,
                )
                await session.execute(
                    text(
                        "INSERT INTO product_presentations(product_id,name,"
                        "price_delta,is_default) "
                        "SELECT id,'TEST Plate',0,true FROM products "
                        "WHERE id<>:product"
                    ),
                    ids,
                )
                await session.execute(
                    text(
                        "INSERT INTO branch_products(branch_id,product_id) "
                        "SELECT :branch,id FROM products WHERE id<>:product"
                    ),
                    ids,
                )
                await session.execute(
                    text(
                        "INSERT INTO customer_favorites(user_id,product_id) "
                        "SELECT :admin,id FROM products ORDER BY id LIMIT 50"
                    ),
                    ids,
                )
                await session.commit()
                s = services(session)
                # Genuine checkout, ledger, release, history and notification writes.
                for _ in range(50):
                    order = await checkout(session, ids)
                    await pay(session, ids, order)
                    await s["kitchen"].start_preparation(
                        staff(ids, "cook"), ids["branch"], order.id
                    )
                await s["cart"].create_cart(owner(ids), ids["branch"])
                for i in range(12):
                    await s["cart"].add_item(
                        owner(ids),
                        ItemCreate(
                            product_id=ids["product"],
                            presentation_id=ids["presentation"],
                            quantity=1,
                            notes="TEST item " + str(i),
                        ),
                    )
                await session.rollback()
                assert (
                    await session.scalar(text("SELECT count(*) FROM products")) == 250
                )
                assert await session.scalar(text("SELECT count(*) FROM orders")) == 50
                assert (
                    await session.scalar(
                        text("SELECT count(*) FROM customer_notifications")
                    )
                    >= 100
                )
                await session.rollback()

                async def measure(label, operation, maximum=None):
                    calls = []

                    def before(
                        connection, cursor, statement, parameters, context, many
                    ):
                        # Store statements/parameters only in memory, never log values.
                        calls.append((statement, parameters))

                    event.listen(engine.sync_engine, "before_cursor_execute", before)
                    start = perf_counter()
                    try:
                        result = await operation
                    finally:
                        duration = (perf_counter() - start) * 1000
                        event.remove(
                            engine.sync_engine, "before_cursor_execute", before
                        )
                    print(
                        json.dumps(
                            {
                                "operation": label,
                                "sql_statements": len(calls),
                                "elapsed_ms": round(duration, 3),
                                "scope": "TEST local service/repository; not HTTP SLA",
                            }
                        )
                    )
                    if maximum is not None:
                        assert len(calls) <= maximum, (label, len(calls), maximum)
                    # Plan the captured read, not a rewritten approximation.
                    reads = [
                        (sql, params)
                        for sql, params in calls
                        if sql.lstrip().upper().startswith(("SELECT", "WITH"))
                    ]
                    if reads:
                        sql, params = reads[-1]
                        connection = await session.connection()
                        result_plan = await connection.exec_driver_sql(
                            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params
                        )
                        plan = result_plan.scalar_one()
                        print(
                            json.dumps(
                                {"operation": label, "explain_analyze_buffers": plan},
                                default=str,
                            )
                        )
                    await session.rollback()
                    return result

                menu = await measure(
                    "menu_250",
                    SQLAlchemyCatalogRepository(session).public_products(ids["branch"]),
                    5,
                )
                assert len(menu) == 250
                cart = await measure(
                    "cart_12",
                    SQLAlchemyCartRepository(session).read_active(ids["customer"]),
                    1,
                )
                assert cart is not None and len(cart[1]) == 12
                for limit in (10, 50):
                    queue = await measure(
                        "kitchen_" + str(limit),
                        s["kitchen"].get_queue(
                            staff(ids, "cook"),
                            ids["branch"],
                            KitchenQueueQuery(limit=limit),
                        ),
                        2,
                    )
                    assert len(queue.preparing) == limit
                notifications = await measure(
                    "notifications_page_50",
                    SQLAlchemyNotificationRepository(session).list_owned(
                        ids["customer"], None, 50
                    ),
                    2,
                )
                assert len(notifications.items) == 50
                favorites = FavoriteService(
                    SQLAlchemyFavoriteRepository(session),
                    CatalogFavoriteGateway(session, s["catalog"]),
                )
                for limit in (10, 50):
                    rows = await measure(
                        "favorites_" + str(limit),
                        favorites.list(staff(ids), ids["branch"], limit),
                        7,
                    )
                    assert len(rows) == limit
                periods = (
                    branch_period(
                        ids["branch"], "TEST A", "America/Lima", utc_now(), None, None
                    ),
                )
                dashboard = await measure(
                    "dashboard",
                    SQLAlchemyAdministrationReadRepository(session).dashboard(periods),
                    1,
                )
                assert dashboard["summary"]["paid_orders_count"] == 50
                assert str(dashboard["summary"]["gross_sales"]) == "2000.00"
                # Exact named/bound statement plan also confirms its reporting bounds.
                statement, params = dashboard_statement(periods)
                plan = await session.scalar(
                    text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(statement)),
                    params,
                )
                assert plan
                await session.rollback()
                result = await measure(
                    "checkout_12",
                    s["orders"].create(
                        owner(ids),
                        "TEST-perf-checkout-12",
                        OrderCreate(
                            mode=OrderMode.LOCAL,
                            payment_method=PaymentMethodType.CASH,
                            table_qr_token=ids["qr"],
                        ),
                    ),
                )
                assert len(result.items) == 12 and str(result.total) == "240.00"

    asyncio.run(scenario())
