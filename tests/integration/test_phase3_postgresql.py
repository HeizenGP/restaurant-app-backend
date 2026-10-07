"""Opt-in only: all Phase 3 DDL and data roll back in a dedicated empty TEST DB."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cart.application.dtos import AddonSelection, ItemCreate, ItemUpdate
from app.modules.cart.application.services import CartService
from app.modules.cart.infrastructure.catalog import CatalogSelectionAdapter
from app.modules.cart.infrastructure.persistence.repositories import (
    SQLAlchemyCartRepository,
)
from app.modules.catalog.application.dtos import CatalogChanges
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.infrastructure.authorization import (
    SQLAlchemyCatalogAuthorization,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.integration.test_phase2_postgresql import migrate_and_test_constraints
from tests.test_phase1_migration import migration_config
from tests.test_phase3_migration import EXPECTED_PHASE_THREE_TABLES

pytestmark = pytest.mark.integration


def migrate_cart_and_check_constraints(connection: Connection):
    ids = migrate_and_test_constraints(connection)
    config = migration_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "0003_cart")
    tables = set(inspect(connection).get_table_names())
    assert EXPECTED_PHASE_THREE_TABLES <= tables and len(tables) == 24
    assert (
        connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0003_cart"
    )
    ids.update(
        {
            name: uuid4()
            for name in ("customer", "other_customer", "cart", "item", "option")
        }
    )
    ids["presentation"] = connection.scalar(
        text("SELECT id FROM product_presentations WHERE name='Plato'")
    )
    connection.execute(
        text(
            "INSERT INTO customers(id,full_name,phone) VALUES "
            "(:customer,'Cart Test','+51900000111'),"
            "(:other_customer,'Other Cart Test','+51900000112')"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO "
            "product_addon_options(id,product_addon_id,name,additional_price) "
            "VALUES (:option,:addon,'Extra',3.50)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO carts(id,customer_id,branch_id) "
            "VALUES (:cart,:customer,:branch)"
        ),
        ids,
    )
    valid_item = (
        "INSERT INTO cart_items(cart_id,product_id,presentation_id,quantity,"
        "base_price_snapshot,presentation_price_snapshot,addons_price_snapshot,"
        "unit_price_snapshot) VALUES (:cart,:product,:presentation,1,20,20,0,20)"
    )
    connection.execute(
        text(
            "INSERT INTO cart_items(id,cart_id,product_id,presentation_id,quantity,"
            "base_price_snapshot,presentation_price_snapshot,addons_price_snapshot,"
            "unit_price_snapshot) VALUES "
            "(:item,:cart,:product,:presentation,2,20,20,3.50,23.50)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO cart_item_addon_options(cart_item_id,product_addon_id,"
            "product_addon_option_id,additional_price_snapshot) "
            "VALUES (:item,:addon,:option,3.50)"
        ),
        ids,
    )
    cases = [
        (
            "INSERT INTO carts(customer_id,branch_id) VALUES (:customer,:branch)",
            "23505",
        ),
        (
            "INSERT INTO carts(customer_id,branch_id,status) VALUES "
            "(:other_customer,:branch,'CHECKOUT')",
            "23514",
        ),
        ("UPDATE cart_items SET quantity=0 WHERE id=:item", "23514"),
        ("UPDATE cart_items SET quantity=-1 WHERE id=:item", "23514"),
        ("UPDATE cart_items SET quantity=10001 WHERE id=:item", "23514"),
        ("UPDATE cart_items SET base_price_snapshot=-1 WHERE id=:item", "23514"),
        (
            "UPDATE cart_items SET presentation_price_snapshot=-1,"
            "unit_price_snapshot=2.50 WHERE id=:item",
            "23514",
        ),
        (
            "UPDATE cart_items SET addons_price_snapshot=-1,"
            "unit_price_snapshot=19 WHERE id=:item",
            "23514",
        ),
        ("UPDATE cart_items SET unit_price_snapshot=-1 WHERE id=:item", "23514"),
        ("UPDATE cart_items SET unit_price_snapshot=100 WHERE id=:item", "23514"),
        ("UPDATE cart_item_addon_options SET additional_price_snapshot=-1", "23514"),
        (
            "INSERT INTO cart_item_addon_options(cart_item_id,product_addon_id,"
            "product_addon_option_id,additional_price_snapshot) "
            "VALUES (:item,:addon,:option,3.50)",
            "23505",
        ),
        (
            "INSERT INTO carts(customer_id,branch_id) VALUES "
            "('00000000-0000-0000-0000-000000000000',:branch)",
            "23503",
        ),
        (
            "INSERT INTO carts(customer_id,branch_id) VALUES "
            "(:other_customer,'00000000-0000-0000-0000-000000000000')",
            "23503",
        ),
        (
            valid_item.replace(":product", "'00000000-0000-0000-0000-000000000000'"),
            "23503",
        ),
        (
            valid_item.replace(
                ":presentation", "'00000000-0000-0000-0000-000000000000'"
            ),
            "23503",
        ),
    ]
    for statement, state in cases:
        with pytest.raises(IntegrityError) as caught:
            with connection.begin_nested():
                connection.execute(text(statement), ids)
        assert getattr(caught.value.orig, "sqlstate", None) == state
    return ids


def test_cart_upgrade_constraints_adapters_and_scoped_downgrade_in_test_database(
    request,
):
    url = guarded_test_url(request)

    async def verify():
        engine = create_async_engine(
            url, echo=False, hide_parameters=True, connect_args={"timeout": 5}
        )
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    objects = await connection.execute(
                        text(
                            "SELECT c.relname FROM pg_class c JOIN pg_namespace n "
                            "ON n.oid=c.relnamespace "
                            "WHERE c.relkind IN ('r','p','v','m','f','S') "
                            "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                            "AND n.nspname NOT LIKE 'pg_toast%'"
                        )
                    )
                    if objects.first() is not None:
                        pytest.fail(
                            "Integration requires an empty dedicated TEST database",
                            pytrace=False,
                        )
                    ids = await connection.run_sync(migrate_cart_and_check_constraints)
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        catalog_repository = SQLAlchemyCatalogRepository(session)
                        catalog = CatalogService(
                            catalog_repository,
                            SQLAlchemyCatalogAuthorization(session),
                            SQLAlchemyAuditRecorder(session),
                        )
                        service = CartService(
                            SQLAlchemyCartRepository(session),
                            CatalogSelectionAdapter(catalog, catalog_repository),
                        )
                        guest = Principal(
                            principal_type=PrincipalType.GUEST,
                            customer_id=ids["customer"],
                        )
                        old = await service.get_cart(guest)
                        assert old.total == Decimal("47.00")
                        admin = Principal(
                            principal_type=PrincipalType.REGISTERED,
                            user_id=ids["actor"],
                        )
                        await catalog.update_product(
                            admin,
                            ids["product"],
                            CatalogChanges({"base_price": Decimal("22")}),
                        )
                        assert (await service.get_cart(guest)).total == Decimal("47.00")
                        recalculated = await service.recalculate_cart(guest)
                        assert recalculated.total == Decimal("51.00")
                        updated = await service.update_item(
                            guest,
                            ids["item"],
                            ItemUpdate(
                                provided_fields=frozenset({"quantity"}), quantity=3
                            ),
                        )
                        assert updated.line_total == Decimal("76.50")
                        assert updated.updated_at > old.items[0].updated_at
                        second = await service.add_item(
                            guest,
                            ItemCreate(
                                product_id=ids["product"],
                                presentation_id=ids["presentation"],
                                quantity=1,
                                addons=(
                                    AddonSelection(ids["addon"], (ids["option"],)),
                                ),
                            ),
                        )
                        assert second.id != ids["item"]
                        await service.delete_item(guest, second.id)
                        assert (
                            await session.scalar(
                                text("SELECT count(*) FROM cart_item_addon_options")
                            )
                            == 1
                        )
                        await service.abandon_cart(guest)
                        new = await service.create_cart(guest, ids["branch"])
                        assert new.id != ids["cart"]
                        await session.rollback()

                    def downgrade_and_check(sync):
                        config = migration_config()
                        config.attributes["connection"] = sync
                        command.downgrade(config, "0002_catalog")
                        assert not EXPECTED_PHASE_THREE_TABLES & set(
                            inspect(sync).get_table_names()
                        )
                        assert (
                            sync.scalar(text("SELECT version_num FROM alembic_version"))
                            == "0002_catalog"
                        )
                        assert sync.scalar(text("SELECT count(*) FROM products")) == 1
                        assert "audit_logs" in inspect(sync).get_table_names()

                    await connection.run_sync(downgrade_and_check)
                finally:
                    await transaction.rollback()
                assert (
                    await connection.run_sync(
                        lambda sync: inspect(sync).get_table_names()
                    )
                    == []
                )
        finally:
            await engine.dispose()

    asyncio.run(verify())
