import asyncio
from unittest.mock import AsyncMock

import pytest

from app.modules.orders.application.errors import InvalidOrderDataError
from app.modules.orders.application.services import OrderSettingsService
from app.modules.orders.domain.models import BranchOrderSettings
from tests.modules.admin.test_services import principal


def service():
    repository = AsyncMock()
    repository.branch_is_active.return_value = True
    repository.get_settings.return_value = BranchOrderSettings(
        branch_id=principal().user_id
    )
    repository.save_settings.side_effect = lambda value: value
    authorization = AsyncMock()
    authorization.has_permission.return_value = True
    clock = AsyncMock()
    audit = AsyncMock()
    return (
        OrderSettingsService(
            repository, authorization, branch_timezones=clock, audit=audit
        ),
        repository,
        clock,
        audit,
    )


def test_existing_settings_endpoint_clock_port_and_audit_share_one_transaction():
    usecase, repo, clock, audit = service()
    branch = repo.get_settings.return_value.branch_id
    result = asyncio.run(
        usecase.update_settings(principal(), branch, {"timezone": "Asia/Tokyo"})
    )
    assert result.timezone == "Asia/Tokyo"
    clock.synchronize_timezone.assert_awaited_once_with(branch, "Asia/Tokyo")
    repo.get_settings.assert_awaited_once_with(branch, lock=True, for_update=True)
    assert usecase._authorization.has_permission.await_count == 2
    repo.commit.assert_awaited_once()
    assert audit.record.await_args.args[0].action == "BRANCH_ORDER_SETTINGS_UPDATED"


@pytest.mark.parametrize("failure", ["clock", "audit", "settings"])
def test_settings_clock_failure_rolls_back_both_owners(failure):
    usecase, repo, clock, audit = service()
    owner, method = (
        (clock, "synchronize_timezone")
        if failure == "clock"
        else (audit, "record")
        if failure == "audit"
        else (repo, "save_settings")
    )
    getattr(owner, method).side_effect = RuntimeError("TEST failure")
    with pytest.raises(RuntimeError):
        asyncio.run(
            usecase.update_settings(
                principal(),
                repo.get_settings.return_value.branch_id,
                {"timezone": "UTC"},
            )
        )
    repo.rollback.assert_awaited_once()
    repo.commit.assert_not_called()


def test_unknown_settings_timezone_never_writes_branch():
    usecase, repo, clock, audit = service()
    with pytest.raises(InvalidOrderDataError):
        asyncio.run(
            usecase.update_settings(
                principal(),
                repo.get_settings.return_value.branch_id,
                {"timezone": "not/known"},
            )
        )
    clock.synchronize_timezone.assert_not_called()
    audit.record.assert_not_called()
