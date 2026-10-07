import asyncio
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.modules.branches.infrastructure.persistence.admin_repository import (
    SQLAlchemyBranchAdministrationRepository,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
    administrative_branch_query,
)
from app.modules.customers.infrastructure.persistence.admin_repository import (
    SQLAlchemyCustomerAdministrationRepository,
)
from app.shared.application.administration import (
    AdministrationConflict,
    AdministrationInvalid,
)
from tests.modules.admin.test_services import customer


def result(*, one=None, mapping=None, mappings=None, rows=None):
    if isinstance(one, SimpleNamespace) and hasattr(one, "created_by_branch_id"):
        vars(one).setdefault("phone", "+51912345678")
        vars(one).setdefault("phone_verified_at", None)
    value = MagicMock()
    value.one.return_value = one
    value.mappings.return_value.one.return_value = mapping
    value.mappings.return_value.one_or_none.return_value = mapping
    value.mappings.return_value.__iter__.return_value = iter(mappings or [])
    value.all.return_value = rows or []
    value.scalars.return_value = []
    return value


def test_customer_scope_origin_or_branch_order_exists_search_bounded_and_escaped():
    session = AsyncMock()
    session.execute.return_value = result(mappings=[])
    repo = SQLAlchemyCustomerAdministrationRepository(session)
    branch = uuid4()
    asyncio.run(repo.list_customers(branch, "Ab%_", 10, 2))
    statement, params = session.execute.await_args.args
    sql = str(statement)
    assert "c.created_by_branch_id=:branch OR EXISTS" in sql
    assert "o.customer_id=c.id AND o.branch_id=:branch" in sql
    assert "ORDER BY c.created_at DESC,c.id DESC LIMIT :limit OFFSET :offset" in sql
    assert params == {"branch": branch, "limit": 10, "offset": 2, "search": "ab\\%\\_%"}
    assert "password" not in sql and "otp" not in sql
    assert "lower(c.full_name) LIKE" in sql


def test_customer_scoped_row_lock_and_no_user_identity_projection():
    row = customer()
    session = AsyncMock()
    session.execute.return_value = result(mapping=asdict(row))
    repo = SQLAlchemyCustomerAdministrationRepository(session)
    found = asyncio.run(repo.get_customer(uuid4(), row.id, lock=True))
    assert found == row
    sql = str(session.execute.await_args.args[0])
    assert "FOR UPDATE OF c" in sql and "EXISTS" in sql
    assert "password_hash" not in sql
    assert "LEFT JOIN users u ON u.id=c.user_id" in sql
    assert "u.first_name,u.last_name" in sql


def test_customer_origin_is_metadata_not_a_new_identity_orm_dependency():
    from sqlalchemy import select

    from app.modules.customers.infrastructure.persistence.models import CustomerModel

    assert "created_by_branch_id" in CustomerModel.__table__.columns
    assert "created_by_branch_id" not in str(select(CustomerModel))


def test_branch_create_rejects_case_folded_legacy_duplicate_before_insert():
    session = AsyncMock()
    session.scalar.return_value = True
    with pytest.raises(AdministrationConflict) as exc:
        asyncio.run(
            SQLAlchemyBranchAdministrationRepository(session).create_branch(
                {"code": "LEGACY", "name": "Duplicate"}
            )
        )
    assert exc.value.code == "BRANCH_CODE_ALREADY_EXISTS"
    assert "lower(code)=lower(:code)" in str(session.scalar.await_args.args[0])
    session.add.assert_not_called()


@pytest.mark.parametrize("duplicate", [True, False])
def test_create_customer_never_creates_user_or_verification(duplicate):
    row = customer()
    session = AsyncMock()
    session.scalar.side_effect = [duplicate, row.id]
    session.execute.return_value = result(mapping=asdict(row))
    repo = SQLAlchemyCustomerAdministrationRepository(session)
    values = {"full_name": row.full_name, "phone": row.phone}
    if duplicate:
        with pytest.raises(AdministrationConflict) as exc:
            asyncio.run(repo.create_customer(uuid4(), values))
        assert exc.value.code == "CUSTOMER_PHONE_ALREADY_EXISTS"
    else:
        asyncio.run(repo.create_customer(uuid4(), values))
        sql = str(session.scalar.await_args_list[1].args[0])
        assert "INSERT INTO customers" in sql
        assert "user_id" not in sql and "phone_verified_at" not in sql
        assert "INSERT INTO users" not in sql


def test_registered_update_locks_customer_before_user_and_updates_both():
    row = customer()
    session = AsyncMock()
    session.scalar.return_value = False
    session.execute.side_effect = [
        result(one=SimpleNamespace(user_id=uuid4())),
        result(
            mapping={
                "first_name": "Old",
                "last_name": None,
                "email": "old@example.test",
                "phone": row.phone,
            }
        ),
        result(),
        result(),
        result(mapping=asdict(row)),
    ]
    asyncio.run(
        SQLAlchemyCustomerAdministrationRepository(session).update_customer(
            uuid4(),
            row.id,
            {"first_name": "New", "last_name": "Name", "email": "new@example.test"},
        )
    )
    calls = session.execute.await_args_list
    assert "customers" in str(calls[0].args[0]) and "FOR UPDATE" in str(
        calls[0].args[0]
    )
    assert "users" in str(calls[1].args[0]) and "FOR UPDATE" in str(calls[1].args[0])
    assert "password_hash" not in str(calls[1].args[0])
    assert "UPDATE users" in str(calls[2].args[0])
    assert calls[3].args[1]["full_name"] == "New Name"
    assert calls[2].args[1]["email"] == calls[3].args[1]["email"]
    session.commit.assert_not_called()


def test_registered_email_removal_must_retain_user_contact_identifier():
    session = AsyncMock()
    session.execute.side_effect = [
        result(one=SimpleNamespace(user_id=uuid4())),
        result(
            mapping={
                "first_name": "Name",
                "last_name": None,
                "email": "old@example.test",
                "phone": None,
            }
        ),
    ]
    with pytest.raises(AdministrationInvalid):
        asyncio.run(
            SQLAlchemyCustomerAdministrationRepository(session).update_customer(
                uuid4(), uuid4(), {"email": None}
            )
        )
    assert session.execute.await_count == 2


@pytest.mark.parametrize("registered,origin_matches", [(True, True), (False, False)])
def test_registered_or_global_guests_are_never_deleted(registered, origin_matches):
    session = AsyncMock()
    branch = uuid4()
    session.execute.return_value = result(
        one=SimpleNamespace(
            user_id=uuid4() if registered else None,
            created_by_branch_id=branch if origin_matches else None,
        )
    )
    with pytest.raises(AdministrationConflict) as exc:
        asyncio.run(
            SQLAlchemyCustomerAdministrationRepository(session).delete_customer(
                branch, uuid4()
            )
        )
    assert exc.value.code == (
        "REGISTERED_CUSTOMER_CANNOT_BE_DELETED"
        if registered
        else "CUSTOMER_HAS_HISTORY"
    )
    assert session.execute.await_count == 1


def test_customer_history_including_addresses_and_otp_blocks_delete():
    session = AsyncMock()
    branch = uuid4()
    session.execute.return_value = result(
        one=SimpleNamespace(user_id=None, created_by_branch_id=branch)
    )
    session.scalar.side_effect = [False, False, True]
    with pytest.raises(AdministrationConflict) as exc:
        asyncio.run(
            SQLAlchemyCustomerAdministrationRepository(session).delete_customer(
                branch, uuid4()
            )
        )
    assert exc.value.code == "CUSTOMER_HAS_HISTORY"
    assert all(
        "DELETE" not in str(call.args[0]) for call in session.execute.await_args_list
    )


def test_customer_fk_last_barrier_is_safe_409():
    session = AsyncMock()
    branch = uuid4()
    session.execute.side_effect = [
        result(one=SimpleNamespace(user_id=None, created_by_branch_id=branch)),
        IntegrityError("test", {}, Exception("constraint")),
    ]
    session.scalar.return_value = False
    with pytest.raises(AdministrationConflict) as exc:
        asyncio.run(
            SQLAlchemyCustomerAdministrationRepository(session).delete_customer(
                branch, uuid4()
            )
        )
    assert exc.value.code == "CUSTOMER_HAS_HISTORY"


def test_verified_guest_has_authentication_history_even_without_orders():
    from tests.modules.admin.test_domain import NOW

    session = AsyncMock()
    branch = uuid4()
    session.execute.return_value = result(
        one=SimpleNamespace(
            user_id=None, created_by_branch_id=branch, phone_verified_at=NOW
        )
    )
    with pytest.raises(AdministrationConflict) as exc:
        asyncio.run(
            SQLAlchemyCustomerAdministrationRepository(session).delete_customer(
                branch, uuid4()
            )
        )
    assert exc.value.code == "CUSTOMER_HAS_HISTORY"
    session.scalar.assert_not_called()


def test_new_branch_requires_official_active_branch_admin_role():
    sql = str(
        administrative_branch_query(uuid4(), "BRANCH_CREATE").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "roles.code = 'ADMIN'" in sql and "roles.scope = 'BRANCH'" in sql


def test_scope_query_checks_current_user_assignment_branch_and_permission():
    sql = str(
        administrative_branch_query(uuid4(), "DASHBOARD_VIEW").compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    for clause in (
        "users.account_status = 'ACTIVE'",
        "users.deleted_at IS NULL",
        "staff_assignments.is_active IS true",
        "staff_assignments.ended_at IS NULL",
        "staff_assignments.assigned_at <= now()",
        "branches.is_active IS true",
        "branches.deleted_at IS NULL",
        "roles.scope = 'BRANCH'",
        "permissions.code = 'DASHBOARD_VIEW'",
    ):
        assert clause in sql
    assert "LIMIT" not in sql


def test_branch_list_is_database_scoped_before_pagination():
    session = AsyncMock()
    session.execute.return_value = result()
    asyncio.run(
        SQLAlchemyBranchAdministrationRepository(session).list_branches(uuid4(), 20, 4)
    )
    sql = str(
        session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "permissions.code = 'BRANCH_VIEW'" in sql
    assert "LIMIT 20 OFFSET 4" in sql
    assert "password_hash" not in sql


def test_staff_candidate_projection_has_no_hash_and_only_active_users():
    session = AsyncMock()
    session.execute.return_value = result(mappings=[])
    asyncio.run(
        SQLAlchemyBranchRepository(session).staff_candidates(uuid4(), "Test%", 10)
    )
    sql = str(
        session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "users.account_status = 'ACTIVE'" in sql
    assert "already_assigned" in sql and "LIMIT 10" in sql
    assert "password_hash" not in sql and "refresh_tokens" not in sql


def test_last_admin_count_excludes_blocked_ended_future_and_other_branch():
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    asyncio.run(
        SQLAlchemyBranchRepository(session).other_active_admin_exists(uuid4(), uuid4())
    )
    sql = str(
        session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "roles.code = 'ADMIN'" in sql
    assert "users.account_status = 'ACTIVE'" in sql
    assert "staff_assignments.assigned_at <= now()" in sql
    assert "staff_assignments.ended_at IS NULL" in sql
    assert "staff_assignments.id !=" in sql


def test_branch_lock_is_taken_before_assignment_lock_in_adapter_contract():
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    asyncio.run(SQLAlchemyBranchRepository(session).lock_branch(uuid4()))
    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "branches" in sql
