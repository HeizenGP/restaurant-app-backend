"""Opt-in PostgreSQL migration, constraints and real adapter transaction checks."""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.catalog.application.dtos import (
    CatalogChanges,
    CategoryCreate,
    PresentationCreate,
    ProductCreate,
)
from app.modules.catalog.application.services import CatalogService
from app.modules.catalog.infrastructure.authorization import (
    SQLAlchemyCatalogAuthorization,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
)
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder
from tests.integration.test_phase1_postgresql import guarded_test_url
from tests.test_phase1_foundation import EXPECTED_PHASE_ONE_TABLES
from tests.test_phase1_migration import migration_config
from tests.test_phase2_migration import EXPECTED_PHASE_TWO_TABLES

pytestmark = pytest.mark.integration


def migrate_and_test_constraints(connection: Connection) -> dict[str, UUID]:
    config = migration_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    assert set(
        inspect(connection).get_table_names()
    ) == EXPECTED_PHASE_ONE_TABLES | EXPECTED_PHASE_TWO_TABLES | {"alembic_version"}
    assert (
        connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0002_catalog"
    )
    assert set(connection.scalars(text("SELECT code FROM permissions"))) == {
        "STAFF_MANAGE",
        "CATALOG_MANAGE",
    }
    ids = {
        name: uuid4() for name in ("category", "product", "branch", "addon", "actor")
    }
    connection.execute(
        text(
            "INSERT INTO categories(id,name,slug) VALUES "
            "(:category,'Arroces','arroces')"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO products(id,category_id,name,slug,base_price) VALUES "
            "(:product,:category,'Aeropuerto','aeropuerto',20.00)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO branches(id,code,name,address_line,district) VALUES "
            "(:branch,'TEST','Test Branch','Test Address','Test District')"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO product_addons(id,product_id,name,max_select) VALUES "
            "(:addon,:product,'Extras',2)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO branch_products(branch_id,product_id) VALUES "
            "(:branch,:product)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO product_images(product_id,url,is_primary) VALUES "
            "(:product,'https://example.test/primary.png',true)"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO "
            "product_presentations(product_id,name,price_delta,is_default) VALUES "
            "(:product,'Plato',0,true)"
        ),
        ids,
    )
    cases = [
        "INSERT INTO products(category_id,name,slug,base_price) VALUES "
        "(:category,'Bad','bad-price',-1)",
        "INSERT INTO categories(name,slug) VALUES ('Duplicate Slug','arroces')",
        "INSERT INTO categories(name,slug) VALUES ('ARROCES','duplicate-name')",
        "INSERT INTO products(category_id,name,slug,base_price) VALUES "
        "(:category,'Duplicate','aeropuerto',1)",
        "INSERT INTO branch_products(branch_id,product_id) VALUES (:branch,:product)",
        "INSERT INTO product_images(product_id,url,is_primary) VALUES "
        "(:product,'https://example.test/second.png',true)",
        "INSERT INTO product_presentations(product_id,name,price_delta,is_default) "
        "VALUES (:product,'Duplicate',0,true)",
        "INSERT INTO product_addons(product_id,name,min_select,max_select) VALUES "
        "(:product,'Bad limits',2,1)",
        "INSERT INTO product_addon_options(product_addon_id,name,additional_price) "
        "VALUES (:addon,'Negative',-1)",
        "INSERT INTO product_presentations(product_id,name,price_delta) VALUES "
        "(:product,'Negative',-1)",
        "UPDATE branch_products SET price_override=-1 WHERE branch_id=:branch",
        "INSERT INTO categories(name,slug,sort_order) VALUES ('Bad "
        "order','bad-order',-1)",
        "INSERT INTO products(category_id,name,slug,base_price) VALUES "
        "('00000000-0000-0000-0000-000000000000','Foreign','foreign',1)",
    ]
    for statement in cases:
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(text(statement), ids)
    # Inactive and archived defaults/primaries don't reserve the active slot.
    connection.execute(
        text(
            "INSERT INTO "
            "product_presentations(product_id,name,price_delta,is_default,is_active) "
            "VALUES (:product,'Inactive default',0,true,false)"
        ),
        ids,
    )
    with pytest.raises(IntegrityError):
        with connection.begin_nested():
            connection.execute(
                text(
                    "UPDATE product_presentations SET is_active=true WHERE "
                    "name='Inactive default'"
                )
            )
    connection.execute(
        text(
            "INSERT INTO product_images(product_id,url,is_primary,deleted_at) VALUES "
            "(:product,'https://example.test/archived.png',true,now())"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO users(id,email,password_hash,first_name) VALUES "
            "(:actor,'migration-test@example.test','test-only-unused-hash','Test')"
        ),
        ids,
    )
    connection.execute(
        text(
            "INSERT INTO staff_assignments(user_id,branch_id,role_id,employee_code) "
            "SELECT :actor,:branch,id,'TEST-ADMIN' FROM roles WHERE code='ADMIN'"
        ),
        ids,
    )
    return ids


def test_phase_two_upgrade_constraints_and_audit_in_clean_test_database(
    request: pytest.FixtureRequest,
) -> None:
    url = guarded_test_url(request)

    async def verify() -> None:
        engine = create_async_engine(
            url, echo=False, hide_parameters=True, connect_args={"timeout": 5}
        )
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    existing = await connection.execute(
                        text(
                            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON "
                            "n.oid=c.relnamespace "
                            "WHERE c.relkind IN ('r','p','v','m','f','S') "
                            "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                            "AND n.nspname NOT LIKE 'pg_toast%'"
                        )
                    )
                    if existing.first() is not None:
                        pytest.fail(
                            "Integration migration requires an empty dedicated test "
                            "database",
                            pytrace=False,
                        )
                    ids = await connection.run_sync(migrate_and_test_constraints)
                    async with AsyncSession(
                        bind=connection,
                        expire_on_commit=False,
                        join_transaction_mode="create_savepoint",
                    ) as session:
                        service = CatalogService(
                            SQLAlchemyCatalogRepository(session),
                            SQLAlchemyCatalogAuthorization(session),
                            SQLAlchemyAuditRecorder(session),
                        )
                        principal = Principal(
                            principal_type=PrincipalType.REGISTERED,
                            user_id=ids["actor"],
                        )
                        category = await service.create_category(
                            principal,
                            CategoryCreate(name="Adapter Test", slug="adapter-test"),
                        )
                        product = await service.create_product(
                            principal,
                            ProductCreate(
                                category_id=category.id,
                                name="Adapter Product",
                                slug="adapter-product",
                                base_price=Decimal("10.00"),
                            ),
                        )
                        await service.create_presentation(
                            principal,
                            product.id,
                            PresentationCreate(
                                name="Configurable",
                                price_delta=Decimal("2.00"),
                                is_default=True,
                            ),
                        )
                        view = await service.product_detail(ids["branch"], product.id)
                        assert view.presentations[0].effective_price == Decimal("12.00")
                        updated = await service.update_product(
                            principal,
                            product.id,
                            CatalogChanges({"base_price": Decimal("11.00")}),
                        )
                        assert updated.updated_at >= product.updated_at
                        assert (
                            await session.scalar(
                                text("SELECT count(*) FROM audit_logs")
                            )
                            == 4
                        )
                        await session.rollback()
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
