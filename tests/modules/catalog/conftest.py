import asyncio
from uuid import uuid4

import pytest

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.catalog.application.services import CatalogService
from tests.modules.catalog.fakes import (
    Grant,
    MemoryAuditRecorder,
    MemoryCatalogAuthorization,
    MemoryCatalogRepository,
)


@pytest.fixture
def catalog_repository() -> MemoryCatalogRepository:
    repository = MemoryCatalogRepository()
    return repository


@pytest.fixture
def branch_a(catalog_repository: MemoryCatalogRepository):
    branch_id = uuid4()
    catalog_repository.branches.add(branch_id)
    return branch_id


@pytest.fixture
def branch_b(catalog_repository: MemoryCatalogRepository):
    branch_id = uuid4()
    catalog_repository.branches.add(branch_id)
    return branch_id


@pytest.fixture
def admin() -> Principal:
    return Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())


@pytest.fixture
def authorization(catalog_repository: MemoryCatalogRepository, branch_a, admin):
    authorization = MemoryCatalogAuthorization(catalog_repository)
    authorization.grants[admin.user_id] = [Grant(branch_id=branch_a)]
    return authorization


@pytest.fixture
def audit(catalog_repository: MemoryCatalogRepository) -> MemoryAuditRecorder:
    return MemoryAuditRecorder(catalog_repository)


@pytest.fixture
def catalog_service(catalog_repository, authorization, audit) -> CatalogService:
    asyncio.run(catalog_repository.commit())
    return CatalogService(catalog_repository, authorization, audit)
