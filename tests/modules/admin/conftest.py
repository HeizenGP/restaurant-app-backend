from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.admin.application.services import AdministrationReadService
from app.modules.admin.infrastructure.read_repository import (
    SQLAlchemyAdministrationReadRepository,
)
from app.modules.admin.presentation.router import get_administration_read_service
from app.modules.auth.application.repository import CustomerIdentityData
from app.modules.branches.application.admin_services import BranchAdministrationService
from app.modules.branches.application.services import BranchService
from app.modules.branches.presentation.admin_router import (
    get_branch_administration_service,
)
from app.modules.branches.presentation.dependencies import get_branch_service
from app.modules.customers.application.admin_services import (
    CustomerAdministrationService,
)
from app.modules.customers.presentation.admin_router import (
    get_customer_administration_service,
)
from app.modules.orders.domain.models import BranchOrderSettings
from app.shared.application.administration import (
    AdministrationConflict,
    AdministrativeBranch,
)
from tests.modules.admin.test_domain import NOW, branch_values
from tests.modules.admin.test_services import customer
from tests.modules.branches.test_branches import MemoryBranchRepository
from tests.modules.notifications.conftest import api as api
from tests.modules.notifications.conftest import setup as setup


@pytest.fixture
def admin_api(api):
    state = api
    auth = AsyncMock()
    state.grants = True
    base = branch_values()
    base.update(
        id=state.setup.branch,
        code="EXISTING",
        city="Tarapoto",
        department="San Martín",
        latitude=None,
        longitude=None,
        phone=None,
        is_active=True,
        deleted_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    state.managed_branches = {state.setup.branch: base}

    async def scopes(actor, permission, *, branch_id=None):
        if state.grants and actor == state.setup.admin.user_id:
            return tuple(
                AdministrativeBranch(b["id"], b["name"], b["timezone"])
                for b in state.managed_branches.values()
                if b["is_active"]
                and b["deleted_at"] is None
                and (branch_id is None or b["id"] == branch_id)
            )
        return ()

    async def permitted(actor, branch, permission):
        return (
            state.grants
            and actor == state.setup.admin.user_id
            and branch in state.managed_branches
            and state.managed_branches[branch]["is_active"]
        )

    auth.authorized_branches.side_effect = scopes
    auth.has_permission.side_effect = permitted

    async def any_permission(actor, permission):
        return bool(await scopes(actor, permission))

    auth.has_any_permission.side_effect = any_permission
    session = SimpleNamespace(execute=AsyncMock())
    session.execute.return_value.mappings = MagicMock(return_value=[])
    read_repo = SQLAlchemyAdministrationReadRepository(session)
    read_service = AdministrationReadService(auth, read_repo)
    owned_read = AsyncMock()
    owned_read.dashboard.side_effect = read_repo.dashboard

    async def config(branch):
        b = state.managed_branches[branch]
        return {
            "branch": {
                k: b[k] for k in ("id", "code", "name", "timezone", "is_active")
            },
            "hours": b["hours"],
            "order_settings": asdict(
                BranchOrderSettings(branch_id=branch, timezone=b["timezone"])
            ),
            "table_count": 0,
            "delivery_zone_count": 0,
            "catalog_summary": {"configured_product_count": 0},
        }

    owned_read.configuration.side_effect = config
    read_service.repository = owned_read
    repo = AsyncMock()
    row = customer()
    repo.list_customers.return_value = [row]
    repo.get_customer.return_value = row

    async def create(branch, values):
        if await state.auth.get_customer_by_phone(values["phone"]):
            raise AdministrationConflict(
                "CUSTOMER_PHONE_ALREADY_EXISTS", "Phone already exists"
            )
        id_ = uuid4()
        identity = CustomerIdentityData(
            id=id_,
            user_id=None,
            full_name=values["full_name"],
            phone=values["phone"],
            email=values.get("email"),
            phone_verified_at=None,
        )
        state.auth.customers[id_] = identity
        return type(row)(
            id=id_,
            full_name=identity.full_name,
            phone=identity.phone,
            email=identity.email,
            is_guest=True,
            phone_verified_at=None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    repo.create_customer.side_effect = create
    repo.commit.side_effect = state.auth.commit
    repo.rollback.side_effect = state.auth.rollback
    audit = AsyncMock()
    customer_service = CustomerAdministrationService(auth, repo, audit)
    staff_repo = MemoryBranchRepository()
    staff_repo.active_ids.add(state.setup.branch)
    staff_repo.branches[state.setup.branch] = staff_repo.branches[staff_repo.branch_a]
    staff_repo.admin = state.setup.admin.user_id
    staff_repo.assignable.add(staff_repo.admin)
    staff_repo.grants = {(staff_repo.admin, state.setup.branch, "STAFF_MANAGE")}
    staff_repo.staff_candidates = AsyncMock(
        return_value=[
            {
                "id": state.setup.admin.user_id,
                "first_name": "Test",
                "last_name": None,
                "email": "admin@example.test",
                "phone": None,
                "account_status": "ACTIVE",
                "already_assigned": True,
                "password_hash": "TEST private never expose",
            }
        ]
    )
    branch_repo = AsyncMock()

    async def list_branches(user, limit, offset):
        return [b for b in state.managed_branches.values() if b["is_active"]][
            offset : offset + limit
        ]

    async def get_branch(branch, *, lock=False):
        return state.managed_branches.get(branch)

    async def create_branch(values):
        b = {**base, **values, "id": uuid4(), "hours": []}
        state.managed_branches[b["id"]] = b
        return b

    async def replace_hours(branch, hours):
        state.managed_branches[branch]["hours"] = hours
        return hours

    async def update_branch(branch, values):
        state.managed_branches[branch].update(values)
        return state.managed_branches[branch]

    async def deactivate(branch):
        state.managed_branches[branch].update(is_active=False, deleted_at=NOW)

    branch_repo.list_branches.side_effect = list_branches
    branch_repo.get_branch.side_effect = get_branch
    branch_repo.create_branch.side_effect = create_branch
    branch_repo.replace_hours.side_effect = replace_hours
    branch_repo.update_branch.side_effect = update_branch
    branch_repo.deactivate_branch.side_effect = deactivate
    orders = AsyncMock()
    orders.has_active_operations.return_value = False
    branch_admin = BranchAdministrationService(auth, branch_repo, orders, audit)
    state.client.app.dependency_overrides[get_branch_administration_service] = lambda: (
        branch_admin
    )
    state.client.app.dependency_overrides[get_administration_read_service] = lambda: (
        read_service
    )
    state.client.app.dependency_overrides[get_customer_administration_service] = (
        lambda: customer_service
    )
    state.client.app.dependency_overrides[get_branch_service] = lambda: BranchService(
        staff_repo, audit
    )
    state.customer_repo = repo
    state.staff_repo = staff_repo
    state.audit = audit
    state.customer_row = row
    state.customer_repo.update_customer.return_value = row
    state.branch_repo = branch_repo
    state.branch_orders = orders
    state.customers_path = (
        "/api/v1/admin/branches/" + str(state.setup.branch) + "/customers"
    )
    return state
