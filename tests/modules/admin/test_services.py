import asyncio
from datetime import date
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.admin.application.services import AdministrationReadService
from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.branches.application.admin_services import BranchAdministrationService
from app.modules.customers.application.admin_ports import AdministrativeCustomer
from app.modules.customers.application.admin_services import (
    CustomerAdministrationService,
)
from app.shared.application.administration import (
    AdministrationConflict,
    AdministrationInvalid,
    AdministrationNotFound,
    AdministrativeBranch,
    AdminPermissionDenied,
)
from tests.modules.admin.test_domain import NOW, branch_values, closed_hours


def principal():
    return Principal(principal_type=PrincipalType.REGISTERED, user_id=uuid4())


def authorization(branch=None):
    auth = AsyncMock()
    auth.has_permission.return_value = True
    auth.has_any_permission.return_value = True
    auth.authorized_branches.return_value = (
        AdministrativeBranch(branch or uuid4(), "Branch", "America/Lima"),
    )
    return auth


def test_dashboard_only_passes_authorized_ids_and_each_local_period():
    auth = authorization()
    second = AdministrativeBranch(uuid4(), "Tokyo", "Asia/Tokyo")
    auth.authorized_branches.return_value += (second,)
    repo = AsyncMock()
    service = AdministrationReadService(auth, repo)
    asyncio.run(service.dashboard(principal(), now=NOW))
    periods = repo.dashboard.await_args.args[0]
    assert len(periods) == 2
    assert periods[0].from_date.day == 6 and periods[1].from_date.day == 7
    assert periods[1].branch_id == second.id
    auth.authorized_branches.assert_awaited_once()
    assert not repo.commit.called


@pytest.mark.parametrize("foreign,empty", [(True, False), (False, True)])
def test_dashboard_no_implicit_global_admin(foreign, empty):
    auth = authorization()
    if empty:
        auth.authorized_branches.return_value = ()
    repo = AsyncMock()
    with pytest.raises(AdminPermissionDenied):
        asyncio.run(
            AdministrationReadService(auth, repo).dashboard(
                principal(), now=NOW, branch_id=uuid4() if foreign else None
            )
        )
    repo.dashboard.assert_not_called()


@pytest.mark.parametrize(
    "first,last",
    [(date(2026, 10, 8), date(2026, 10, 7)), (date(2026, 1, 1), date(2026, 2, 1))],
)
def test_dashboard_invalid_period_is_safe_422(first, last):
    repo = AsyncMock()
    with pytest.raises(AdministrationInvalid) as exc:
        asyncio.run(
            AdministrationReadService(authorization(), repo).dashboard(
                principal(), now=NOW, from_date=first, to_date=last
            )
        )
    assert exc.value.code == "DASHBOARD_INVALID_PERIOD"
    repo.dashboard.assert_not_called()


def test_guest_cannot_access_read_models():
    auth = authorization()
    repo = AsyncMock()
    with pytest.raises(AdminPermissionDenied):
        asyncio.run(
            AdministrationReadService(auth, repo).dashboard(
                Principal(principal_type=PrincipalType.GUEST, customer_id=uuid4()),
                now=NOW,
            )
        )
    auth.authorized_branches.assert_not_called()


def customer():
    return AdministrativeCustomer(
        id=uuid4(),
        full_name="Customer",
        phone="+51912345678",
        email=None,
        is_guest=True,
        phone_verified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize("action", ["CREATE", "UPDATE", "DELETE"])
def test_customer_mutations_transactional_audit(action):
    row = customer()
    repo = AsyncMock()
    repo.get_customer.return_value = row
    repo.create_customer.return_value = row
    repo.update_customer.return_value = row
    audit = AsyncMock()
    service = CustomerAdministrationService(authorization(), repo, audit)
    values = (
        {"full_name": "Changed", "phone": row.phone}
        if action == "CREATE"
        else {"full_name": "Changed"}
        if action == "UPDATE"
        else {}
    )
    result = asyncio.run(
        service.mutate(
            principal(), uuid4(), action, values, None if action == "CREATE" else row.id
        )
    )
    assert result == (None if action == "DELETE" else row)
    record = audit.record.await_args.args[0]
    assert (
        record.action
        == "ADMIN_CUSTOMER_"
        + {"CREATE": "CREATED", "UPDATE": "UPDATED", "DELETE": "DELETED"}[action]
    )
    assert row.phone not in str(record.after_state)
    repo.commit.assert_awaited_once()


@pytest.mark.parametrize("action", ["CREATE", "UPDATE", "DELETE"])
def test_customer_audit_failure_rolls_back(action):
    row = customer()
    repo = AsyncMock()
    repo.get_customer.return_value = row
    repo.create_customer.return_value = row
    repo.update_customer.return_value = row
    audit = AsyncMock()
    audit.record.side_effect = RuntimeError("test failure")
    values = (
        {"full_name": "Changed", "phone": row.phone}
        if action == "CREATE"
        else {"full_name": "Changed"}
        if action == "UPDATE"
        else {}
    )
    with pytest.raises(RuntimeError):
        asyncio.run(
            CustomerAdministrationService(authorization(), repo, audit).mutate(
                principal(),
                uuid4(),
                action,
                values,
                None if action == "CREATE" else row.id,
            )
        )
    repo.rollback.assert_awaited_once()
    repo.commit.assert_not_called()


@pytest.mark.parametrize("permission", ["CUSTOMER_VIEW", "CUSTOMER_MANAGE"])
def test_customer_authorization_before_resource_lookup(permission):
    auth = authorization()
    auth.has_permission.return_value = False
    repo = AsyncMock()
    service = CustomerAdministrationService(auth, repo, AsyncMock())
    with pytest.raises(AdminPermissionDenied):
        if permission == "CUSTOMER_VIEW":
            asyncio.run(service.get(principal(), uuid4(), uuid4()))
        else:
            asyncio.run(service.mutate(principal(), uuid4(), "DELETE", {}, uuid4()))
    repo.get_customer.assert_not_called()


def test_authorized_missing_customer_is_404():
    repo = AsyncMock()
    repo.get_customer.return_value = None
    with pytest.raises(AdministrationNotFound) as exc:
        asyncio.run(
            CustomerAdministrationService(authorization(), repo, AsyncMock()).get(
                principal(), uuid4(), uuid4()
            )
        )
    assert exc.value.code == "ADMIN_CUSTOMER_NOT_FOUND"


def branch_service():
    repo = AsyncMock()
    repo.get_branch.return_value = {
        "id": uuid4(),
        "is_active": True,
        "deleted_at": None,
    }
    repo.create_branch.return_value = {
        "id": uuid4(),
        "code": "NEW",
        "timezone": "America/Lima",
    }
    orders = AsyncMock()
    orders.has_active_operations.return_value = False
    return BranchAdministrationService(authorization(), repo, orders, AsyncMock())


def test_branch_create_initializes_all_owners_and_creator():
    service = branch_service()
    asyncio.run(service.create(principal(), branch_values()))
    service.repository.replace_hours.assert_awaited_once()
    service.orders.initialize.assert_awaited_once()
    service.repository.assign_creator.assert_awaited_once()
    service.repository.commit.assert_awaited_once()
    assert service.audit.record.await_args.args[0].action == "BRANCH_CREATED"


@pytest.mark.parametrize(
    "failure",
    [
        "create_branch",
        "replace_hours",
        "initialize",
        "assign_creator",
        "record",
        "commit",
    ],
)
def test_branch_create_failure_rolls_back_every_part(failure):
    service = branch_service()
    owner = (
        service.orders
        if failure == "initialize"
        else service.audit
        if failure == "record"
        else service.repository
    )
    getattr(owner, failure).side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError):
        asyncio.run(service.create(principal(), branch_values()))
    service.repository.rollback.assert_awaited_once()


def test_new_branch_creation_requires_existing_active_permission():
    service = branch_service()
    service.authorization.has_any_permission.return_value = False
    with pytest.raises(AdminPermissionDenied):
        asyncio.run(service.create(principal(), branch_values()))
    service.repository.create_branch.assert_not_called()


def test_branch_timezone_updates_orders_settings_atomically():
    service = branch_service()
    id_ = uuid4()
    asyncio.run(service.mutate(principal(), id_, "UPDATE", {"timezone": "Asia/Tokyo"}))
    service.orders.synchronize_timezone.assert_awaited_once_with(id_, "Asia/Tokyo")
    service.repository.get_branch.assert_awaited_with(id_, lock=True)
    service.repository.commit.assert_awaited_once()


def test_invalid_timezone_never_writes():
    service = branch_service()
    with pytest.raises(AdministrationInvalid) as exc:
        asyncio.run(
            service.mutate(principal(), uuid4(), "UPDATE", {"timezone": "not/a/zone"})
        )
    assert exc.value.code == "BRANCH_TIMEZONE_INVALID"
    service.repository.update_branch.assert_not_called()
    service.repository.rollback.assert_awaited_once()


def test_active_operations_prevent_branch_deactivation():
    service = branch_service()
    service.orders.has_active_operations.return_value = True
    with pytest.raises(AdministrationConflict) as exc:
        asyncio.run(service.mutate(principal(), uuid4(), "DELETE", {}))
    assert exc.value.code == "BRANCH_HAS_ACTIVE_OPERATIONS"
    service.repository.deactivate_branch.assert_not_called()
    service.repository.rollback.assert_awaited_once()


def test_branch_soft_deletion_preserves_staff_and_records():
    service = branch_service()
    id_ = uuid4()
    asyncio.run(service.mutate(principal(), id_, "DELETE", {}))
    service.repository.deactivate_branch.assert_awaited_once_with(id_)
    assert not service.repository.delete_staff.called
    assert service.audit.record.await_args.args[0].action == "BRANCH_DEACTIVATED"


def test_hours_full_replacement_audited_without_address():
    service = branch_service()
    hours = closed_hours()
    asyncio.run(service.mutate(principal(), uuid4(), "HOURS", {"hours": hours}))
    assert service.audit.record.await_args.args[0].action == "BRANCH_HOURS_UPDATED"
    assert "address" not in str(service.audit.record.await_args.args[0].after_state)
