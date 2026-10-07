import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.dtos import (
    BranchProductConfig,
    CatalogChanges,
    CategoryCreate,
)
from app.modules.catalog.application.errors import CatalogConflictError
from app.modules.catalog.domain.models import ProductImage, ProductPresentation
from app.modules.catalog.infrastructure.authorization import (
    SQLAlchemyCatalogAuthorization,
)
from app.modules.catalog.infrastructure.persistence.models import (
    BranchProductModel,
    CategoryModel,
    ProductAddonModel,
    ProductAddonOptionModel,
    ProductImageModel,
    ProductModel,
    ProductPresentationModel,
)
from app.modules.catalog.infrastructure.persistence.repositories import (
    SQLAlchemyCatalogRepository,
    to_entity,
)
from app.shared.application.audit import AuditRecord
from app.shared.infrastructure.audit.models import AuditLogModel
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder


def result(
    *, rows: list | None = None, scalar: object = None, scalars: list | None = None
) -> MagicMock:
    value = MagicMock()
    value.all.return_value = rows or []
    value.scalar_one_or_none.return_value = scalar
    value.scalar_one.return_value = scalar
    value.scalars.return_value.all.return_value = scalars or []
    value.scalars.return_value.__iter__.return_value = iter(scalars or [])
    return value


def session() -> MagicMock:
    value = MagicMock(spec=AsyncSession)
    value.execute = AsyncMock(return_value=result())
    value.get = AsyncMock()
    value.flush = AsyncMock()
    value.refresh = AsyncMock()
    value.commit = AsyncMock()
    value.rollback = AsyncMock()
    return value


def compiled(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_public_menu_batches_children_in_constant_query_count():
    db = session()
    category = CategoryModel(name="Arroces", slug="arroces")
    products = [
        ProductModel(
            category_id=category.id,
            name=f"Product {i}",
            slug=f"product-{i}",
            base_price=Decimal("20.00"),
        )
        for i in range(50)
    ]
    presentations = [
        ProductPresentationModel(
            product_id=p.id, name="Selectable", price_delta=Decimal("0.00")
        )
        for p in products
    ]
    addon = ProductAddonModel(product_id=products[0].id, name="Extras")
    option = ProductAddonOptionModel(
        product_addon_id=addon.id, name="Free", additional_price=Decimal("0.00")
    )
    db.execute.side_effect = [
        result(rows=[(p, category, None) for p in products]),
        result(scalars=[]),
        result(scalars=presentations),
        result(scalars=[addon]),
        result(scalars=[option]),
    ]
    rows = asyncio.run(SQLAlchemyCatalogRepository(db).public_products(uuid4()))
    assert len(rows) == 50 and db.execute.await_count == 5
    root_sql = compiled(db.execute.await_args_list[0].args[0])
    assert "LEFT OUTER JOIN branch_products" in root_sql and "EXISTS" in root_sql
    assert "products.is_active IS true" in root_sql
    assert "categories.deleted_at IS NULL" in root_sql
    assert "branch_products.is_available IS true" not in root_sql
    assert "ORDER BY categories.sort_order" in root_sql
    assert len(rows[0].options) == 1
    for call in db.execute.await_args_list[1:]:
        assert " IN " in compiled(call.args[0])
        assert "deleted_at IS NULL" in compiled(call.args[0])


def test_empty_menu_does_not_query_children():
    db = session()
    assert asyncio.run(SQLAlchemyCatalogRepository(db).public_products(uuid4())) == []
    db.execute.assert_awaited_once()


@pytest.mark.parametrize(
    "method,parent_field",
    [
        ("get_image", "product_images.product_id"),
        ("get_presentation", "product_presentations.product_id"),
        ("get_addon", "product_addons.product_id"),
        ("get_option", "product_addon_options.product_addon_id"),
    ],
)
def test_child_lookups_filter_parent_and_archive(method: str, parent_field: str):
    db = session()
    asyncio.run(getattr(SQLAlchemyCatalogRepository(db), method)(uuid4(), uuid4()))
    sql = compiled(db.execute.await_args.args[0])
    assert parent_field in sql and "deleted_at IS NULL" in sql


@pytest.mark.parametrize("method", ["get_category", "get_product"])
def test_mutation_parent_locks_refresh_stale_identity_map(method: str):
    db = session()
    asyncio.run(getattr(SQLAlchemyCatalogRepository(db), method)(uuid4(), lock=True))
    query = db.execute.await_args.args[0]
    assert "FOR UPDATE" in compiled(query)
    assert query.get_execution_options()["populate_existing"] is True


@pytest.mark.parametrize("entity", ["image", "presentation"])
def test_primary_default_update_excludes_target_so_unrelated_patch_preserves_flag(
    entity: str,
):
    db = session()
    product_id = uuid4()
    if entity == "image":
        model = ProductImageModel(
            product_id=product_id, url="https://example.test/a.png", is_primary=True
        )
        domain = to_entity(model, ProductImage)
        changes = CatalogChanges({"alt_text": "Comida"})
    else:
        model = ProductPresentationModel(
            product_id=product_id,
            name="Default",
            price_delta=Decimal("0"),
            is_default=True,
        )
        domain = to_entity(model, ProductPresentation)
        changes = CatalogChanges({"name": "Changed"})
    db.get.return_value = model
    updated = asyncio.run(
        getattr(SQLAlchemyCatalogRepository(db), f"update_{entity}")(domain, changes)
    )
    assert getattr(updated, "is_primary" if entity == "image" else "is_default")
    clearing = db.execute.await_args.args[0]
    params = clearing.compile(dialect=postgresql.dialect()).params
    assert model.id in params.values()
    assert "deleted_at IS NULL" in compiled(clearing)
    db.commit.assert_not_awaited()


def test_branch_upsert_is_atomic_and_populates_returned_current_row():
    db = session()
    branch_id, product_id = uuid4(), uuid4()
    model = BranchProductModel(
        branch_id=branch_id,
        product_id=product_id,
        is_available=False,
        price_override=Decimal("22"),
    )
    db.execute.return_value = result(scalar=model)
    returned = asyncio.run(
        SQLAlchemyCatalogRepository(db).upsert_branch_product(
            branch_id, product_id, BranchProductConfig(False, Decimal("22"))
        )
    )
    query = db.execute.await_args.args[0]
    sql = compiled(query)
    assert "ON CONFLICT ON CONSTRAINT uq_branch_products_branch_id_product_id" in sql
    assert "RETURNING branch_products.id" in sql
    assert query.get_execution_options()["populate_existing"] is True
    assert returned.price_override == Decimal("22")
    db.commit.assert_not_awaited()


class ConstraintViolation(Exception):
    def __init__(self, constraint: str):
        super().__init__("private SQL params")
        self.constraint_name = constraint


@pytest.mark.parametrize(
    "constraint,code",
    [
        ("uq_categories_slug", "CATEGORY_SLUG_CONFLICT"),
        ("uq_categories_name", "CATEGORY_NAME_CONFLICT"),
        ("uq_products_slug", "PRODUCT_SLUG_CONFLICT"),
        ("unknown_constraint", "CATALOG_CONFLICT"),
    ],
)
def test_integrity_errors_are_safe_and_specific(constraint: str, code: str):
    db = session()
    db.flush.side_effect = IntegrityError(
        "private SQL", {"password": "private"}, ConstraintViolation(constraint)
    )
    with pytest.raises(CatalogConflictError) as raised:
        asyncio.run(
            SQLAlchemyCatalogRepository(db).create_category(
                CategoryCreate(name="Example", slug="example")
            )
        )
    assert raised.value.code == code and "private" not in str(raised.value)
    assert raised.value.__suppress_context__


def test_global_permission_query_checks_admin_current_account_branch_and_grant():
    db = session()
    asyncio.run(SQLAlchemyCatalogAuthorization(db).can_manage(uuid4(), None))
    sql = compiled(db.execute.await_args.args[0])
    params = db.execute.await_args.args[0].compile(dialect=postgresql.dialect()).params
    for fragment in (
        "JOIN users",
        "JOIN branches",
        "JOIN roles",
        "JOIN permissions",
        "staff_assignments.ended_at IS NULL",
        "users.deleted_at IS NULL",
        "branches.deleted_at IS NULL",
    ):
        assert fragment in sql
    assert {"ADMIN", "BRANCH", "ACTIVE", "CATALOG_MANAGE"} <= set(params.values())


def test_branch_permission_query_scopes_the_requested_branch():
    db = session()
    branch_id = uuid4()
    asyncio.run(SQLAlchemyCatalogAuthorization(db).can_manage(uuid4(), branch_id))
    query = db.execute.await_args.args[0]
    assert branch_id in query.compile(dialect=postgresql.dialect()).params.values()
    assert "staff_assignments.branch_id =" in compiled(query)


def test_audit_adapter_uses_callers_session_without_committing_or_flushing():
    db = session()
    event = AuditRecord(
        actor_user_id=uuid4(),
        branch_id=None,
        action="CATEGORY_CREATED",
        entity_type="CATEGORY",
        entity_id=uuid4(),
        before_state=None,
        after_state={"name": "Arroces"},
    )
    asyncio.run(SQLAlchemyAuditRecorder(db).record(event))
    model = db.add.call_args.args[0]
    assert (
        isinstance(model, AuditLogModel) and model.actor_user_id == event.actor_user_id
    )
    assert model.after_state == {"name": "Arroces"}
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
