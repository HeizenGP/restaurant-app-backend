from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.auth.domain.models import Principal
from app.modules.branches.application.admin_ports import (
    BranchAdministrationRepository,
    BranchOrderConfiguration,
)
from app.modules.branches.domain.administration import branch_fields, validate_hours
from app.shared.application.administration import (
    AdministrationAuthorization,
    AdministrationConflict,
    AdministrationInvalid,
    AdministrationNotFound,
    AdminPermissionDenied,
    administrative_actor,
    require_administration,
)
from app.shared.application.audit import AuditRecord, AuditRecorder


class BranchAdministrationService:
    def __init__(
        self,
        authorization: AdministrationAuthorization,
        repository: BranchAdministrationRepository,
        orders: BranchOrderConfiguration,
        audit: AuditRecorder,
    ) -> None:
        self.authorization = authorization
        self.repository = repository
        self.orders = orders
        self.audit = audit

    async def list(self, principal: Principal, limit: int, offset: int) -> list[dict]:
        actor = administrative_actor(principal)
        if not await self.authorization.has_any_permission(actor, "BRANCH_VIEW"):
            raise AdminPermissionDenied()
        return await self.repository.list_branches(actor, limit, offset)

    async def get(self, principal: Principal, branch_id: UUID) -> dict:
        await require_administration(
            self.authorization, principal, branch_id, "BRANCH_VIEW"
        )
        return await self._branch(branch_id)

    async def _branch(self, branch_id: UUID, *, lock: bool = False) -> dict:
        branch = await self.repository.get_branch(branch_id, lock=lock)
        if (
            branch is None
            or not branch["is_active"]
            or branch["deleted_at"] is not None
        ):
            raise AdministrationNotFound("BRANCH_NOT_FOUND", "Branch not found")
        return branch

    @staticmethod
    def _timezone(value: str) -> None:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise AdministrationInvalid(
                "BRANCH_TIMEZONE_INVALID", "Unknown IANA timezone"
            ) from None

    async def create(self, principal: Principal, values: dict) -> dict:
        actor = administrative_actor(principal)
        if not await self.authorization.has_any_permission(actor, "BRANCH_CREATE"):
            raise AdminPermissionDenied()
        try:
            values = branch_fields(values, creating=True)
        except ValueError as exc:
            raise AdministrationInvalid("INVALID_REQUEST_DATA", str(exc)) from None
        self._timezone(values["timezone"])
        values = dict(values)
        hours = values.pop("hours")
        try:
            branch = await self.repository.create_branch(values)
            await self.repository.replace_hours(branch["id"], hours)
            await self.orders.initialize(branch["id"], branch["timezone"])
            await self.repository.assign_creator(branch["id"], actor)
            await self.audit.record(
                AuditRecord(
                    actor_user_id=actor,
                    branch_id=branch["id"],
                    action="BRANCH_CREATED",
                    entity_type="BRANCH",
                    entity_id=branch["id"],
                    before_state=None,
                    after_state={"code": branch["code"], "is_active": True},
                )
            )
            result = await self.repository.get_branch(branch["id"])
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    async def mutate(
        self, principal: Principal, branch_id: UUID, action: str, values: dict
    ) -> dict | list[dict] | None:
        actor = await require_administration(
            self.authorization, principal, branch_id, "BRANCH_MANAGE"
        )
        try:
            branch = await self._branch(branch_id, lock=True)
            # Recheck grants under the branch lock before writing.
            await require_administration(
                self.authorization, principal, branch_id, "BRANCH_MANAGE"
            )
            if action == "UPDATE":
                try:
                    values = branch_fields(values, creating=False)
                except ValueError as exc:
                    raise AdministrationInvalid(
                        "INVALID_REQUEST_DATA", str(exc)
                    ) from None
                if "timezone" in values:
                    self._timezone(values["timezone"])
                result = await self.repository.update_branch(branch_id, values)
                if "timezone" in values:
                    await self.orders.synchronize_timezone(
                        branch_id, values["timezone"]
                    )
                suffix = "UPDATED"
            elif action == "HOURS":
                try:
                    validate_hours(values["hours"])
                except ValueError as exc:
                    raise AdministrationInvalid(
                        "INVALID_REQUEST_DATA", str(exc)
                    ) from None
                result = await self.repository.replace_hours(branch_id, values["hours"])
                suffix = "HOURS_UPDATED"
            elif action == "DELETE":
                if await self.orders.has_active_operations(branch_id):
                    raise AdministrationConflict(
                        "BRANCH_HAS_ACTIVE_OPERATIONS", "Branch has pending operations"
                    )
                await self.repository.deactivate_branch(branch_id)
                result = None
                suffix = "DEACTIVATED"
            else:
                raise ValueError("Unknown branch action")
            await self.audit.record(
                AuditRecord(
                    actor_user_id=actor,
                    branch_id=branch_id,
                    action="BRANCH_" + suffix,
                    entity_type="BRANCH",
                    entity_id=branch_id,
                    before_state={"is_active": branch["is_active"]},
                    after_state={f"changed_{key}": True for key in values}
                    if result is not None
                    else {"is_active": False},
                )
            )
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise
