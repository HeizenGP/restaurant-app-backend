"""TEST-only committed schema, fresh Alembic chain and real slice composition."""

import re
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cart.application.dtos import ItemCreate
from app.modules.cart.presentation.dependencies import get_cart_service
from app.modules.catalog.presentation.dependencies import get_catalog_service
from app.modules.fulfillment.presentation.dependencies import get_fulfillment_service
from app.modules.kitchen.presentation.dependencies import get_kitchen_service
from app.modules.orders.application.dtos import OrderCreate
from app.modules.orders.domain.models import OrderMode, PaymentMethodType
from app.modules.orders.presentation.dependencies import get_order_service
from app.modules.payments.presentation.dependencies import get_payment_service
from app.shared.domain.time import utc_now
from tests.integration.test_phase9_postgresql import require_empty
from tests.modules.payments.fakes import MemoryDatabase, TestGateway, signed_event
from tests.test_phase1_migration import migration_config


def fresh_upgrade(sync):
    config = migration_config()
    config.attributes["connection"] = sync
    command.upgrade(config, "head")
    assert (
        sync.scalar(text("SELECT version_num FROM alembic_version"))
        == "0011_customer_extras"
    )
    assert len(inspect(sync).get_table_names()) == 60
    assert sync.scalar(text("SELECT count(*) FROM users")) == 0


@asynccontextmanager
async def fresh_database(url):
    schema = "phase12_test_" + uuid4().hex
    assert re.fullmatch(r"phase12_test_[a-f0-9]{32}", schema)
    engine = create_async_engine(
        url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args={
            "timeout": 5,
            "server_settings": {
                "search_path": schema + ",public",
                "lock_timeout": "5s",
                "statement_timeout": "30s",
            },
        },
    )
    committed = False
    try:
        async with engine.begin() as connection:
            await require_empty(connection)
            await connection.execute(text('CREATE SCHEMA "' + schema + '"'))
            # NO create_all/stamp/manual extension prerequisites; 0001 owns them.
            await connection.run_sync(fresh_upgrade)
        committed = True
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        if committed:
            async with engine.begin() as connection:
                assert (
                    await connection.scalar(
                        text(
                            "SELECT pg_get_userbyid(nspowner)=current_user "
                            "FROM pg_namespace WHERE nspname=:schema"
                        ),
                        {"schema": schema},
                    )
                    is True
                )
                # Only this newly-created UUID schema, never public/normal DB.
                await connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
                await require_empty(connection)
        await engine.dispose()


async def seed(factory):
    ids = {
        name: uuid4()
        for name in (
            "branch",
            "branch_b",
            "admin",
            "admin_b",
            "cook",
            "customer",
            "customer_b",
            "category",
            "product",
            "presentation",
            "table",
            "qr",
            "address",
        )
    }
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO branches(id,code,name,address_line,district) VALUES "
                "(:branch,'TEST-A','TEST A','TEST Address A','Tarapoto'),"
                "(:branch_b,'TEST-B','TEST B','TEST Address B','Tarapoto')"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO users(id,email,password_hash,first_name) VALUES "
                "(:admin,'phase12-admin-a@example.com',"
                "'TEST-only-unused','TEST Admin A'),"
                "(:admin_b,'phase12-admin-b@example.com',"
                "'TEST-only-unused','TEST Admin B'),"
                "(:cook,'phase12-cook@example.com','TEST-only-unused','TEST Cook')"
            ),
            ids,
        )
        for user, branch, role in (
            ("admin", "branch", "ADMIN"),
            ("admin_b", "branch_b", "ADMIN"),
            ("cook", "branch", "KITCHEN"),
        ):
            await session.execute(
                text(
                    "INSERT INTO staff_assignments(user_id,branch_id,role_id,"
                    "employee_code) SELECT :user,:branch,id,:code "
                    "FROM roles WHERE code=:role"
                ),
                {
                    "user": ids[user],
                    "branch": ids[branch],
                    "code": "TEST-" + user,
                    "role": role,
                },
            )
        await session.execute(
            text(
                "INSERT INTO customers(id,full_name,phone) VALUES "
                "(:customer,'TEST Customer A','+519000001201'),"
                "(:customer_b,'TEST Customer B','+519000001202')"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO categories(id,name,slug) VALUES "
                "(:category,'TEST Category','phase12-test')"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO products(id,category_id,name,slug,base_price) VALUES "
                "(:product,:category,'TEST Product','phase12-product',20.00)"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO product_presentations(id,product_id,name,is_default) "
                "VALUES (:presentation,:product,'TEST Plate',true)"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO branch_products(branch_id,product_id) VALUES "
                "(:branch,:product),(:branch_b,:product)"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO restaurant_tables(id,branch_id,label,qr_token) "
                "VALUES (:table,:branch,'TEST Table',:qr)"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO branch_hours(branch_id,day_of_week,open_time,"
                "close_time) SELECT :branch,i,'00:00'::time,'23:59:59'::time "
                "FROM generate_series(0,6) i"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO branch_order_settings(branch_id,default_prep_minutes,"
                "queue_delay_per_order_minutes,pickup_buffer_minutes) "
                "VALUES (:branch,20,0,5)"
            ),
            ids,
        )
        await session.execute(
            text(
                "INSERT INTO customer_addresses(id,customer_id,label,"
                "recipient_name,recipient_phone,address_line,district) VALUES "
                "(:address,:customer,'TEST Home','TEST Customer A',"
                "'+519000001201','TEST private address','Tarapoto')"
            ),
            ids,
        )
        await session.commit()
    return ids


def owner(ids, foreign=False):
    return Principal(
        principal_type=PrincipalType.GUEST,
        customer_id=ids["customer_b" if foreign else "customer"],
    )


def staff(ids, who="admin"):
    return Principal(principal_type=PrincipalType.REGISTERED, user_id=ids[who])


class DatabaseAwareGateway(TestGateway):
    def __init__(self, session):
        super().__init__(MemoryDatabase())
        self.session = session

    async def create_payment_attempt(self, request):
        assert not self.session.in_transaction()
        return await super().create_payment_attempt(request)


def services(session):
    catalog = get_catalog_service(session)
    payments = get_payment_service(session, DatabaseAwareGateway(session))
    return {
        "catalog": catalog,
        "cart": get_cart_service(session, catalog),
        "orders": get_order_service(session, catalog),
        "payments": payments,
        "kitchen": get_kitchen_service(session),
        "fulfillment": get_fulfillment_service(session),
    }


async def checkout(session, ids, mode=OrderMode.LOCAL, *, key=None):
    s = services(session)
    await s["cart"].create_cart(owner(ids), ids["branch"])
    await s["cart"].add_item(
        owner(ids),
        ItemCreate(
            product_id=ids["product"],
            presentation_id=ids["presentation"],
            quantity=2,
            notes="TEST no onion",
            addons=(),
        ),
    )
    command = OrderCreate(
        mode=mode,
        payment_method=PaymentMethodType.CASH
        if mode == OrderMode.LOCAL
        else PaymentMethodType.ONLINE,
        table_qr_token=ids["qr"] if mode == OrderMode.LOCAL else None,
        requested_pickup_at=utc_now() + timedelta(hours=2)
        if mode == OrderMode.PICKUP
        else None,
        address_id=ids["address"] if mode == OrderMode.DELIVERY else None,
    )
    return await s["orders"].create(
        owner(ids), key or "phase12-" + uuid4().hex, command
    )


async def pay(session, ids, order):
    s = services(session)
    if order.mode == OrderMode.LOCAL:
        result = await s["payments"].confirm_cash(staff(ids), ids["branch"], order.id)
        await s["orders"].confirm_cash_release(staff(ids), order.id)
        return result
    result = await s["payments"].initiate_online(
        owner(ids), order.id, "TEST-pay-" + str(order.id)
    )
    body, headers = signed_event(
        result.attempt,
        amount=str(order.total),
        event=str(order.id),
        occurred_at=utc_now(),
    )
    await s["payments"].webhook(s["payments"].gateway.provider_code, body, headers)
    return result
