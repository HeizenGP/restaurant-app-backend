from uuid import UUID

from app.modules.auth.domain.models import Principal
from app.modules.customers.application.admin_ports import (
    AdministrativeCustomer,
    CustomerAdministrationRepository,
)
from app.modules.customers.domain.administration import customer_fields
from app.shared.application.administration import (
    AdministrationAuthorization,
    AdministrationInvalid,
    AdministrationNotFound,
    require_administration,
)
from app.shared.application.audit import AuditRecord, AuditRecorder


class CustomerAdministrationService:
    def __init__(
        self,
        authorization: AdministrationAuthorization,
        repository: CustomerAdministrationRepository,
        audit: AuditRecorder,
    ) -> None:
        self.authorization = authorization
        self.repository = repository
        self.audit = audit

    async def list(
        self,
        principal: Principal,
        branch_id: UUID,
        search: str | None,
        limit: int,
        offset: int,
    ) -> list[AdministrativeCustomer]:
        await require_administration(
            self.authorization, principal, branch_id, "CUSTOMER_VIEW"
        )
        return await self.repository.list_customers(branch_id, search, limit, offset)

    async def get(
        self, principal: Principal, branch_id: UUID, customer_id: UUID
    ) -> AdministrativeCustomer:
        await require_administration(
            self.authorization, principal, branch_id, "CUSTOMER_VIEW"
        )
        return await self._visible(branch_id, customer_id)

    async def _visible(
        self, branch_id: UUID, customer_id: UUID, *, lock: bool = False
    ) -> AdministrativeCustomer:
        customer = await self.repository.get_customer(branch_id, customer_id, lock=lock)
        if customer is None:
            raise AdministrationNotFound(
                "ADMIN_CUSTOMER_NOT_FOUND", "Customer not found"
            )
        return customer

    async def mutate(
        self,
        principal: Principal,
        branch_id: UUID,
        action: str,
        values: dict,
        customer_id: UUID | None = None,
    ) -> AdministrativeCustomer | None:
        actor = await require_administration(
            self.authorization, principal, branch_id, "CUSTOMER_MANAGE"
        )
        if action != "DELETE":
            try:
                values = customer_fields(values, creating=action == "CREATE")
            except ValueError as exc:
                raise AdministrationInvalid("INVALID_REQUEST_DATA", str(exc)) from None
        try:
            before = (
                await self._visible(branch_id, customer_id, lock=True)
                if customer_id
                else None
            )
            if action == "CREATE":
                result = await self.repository.create_customer(branch_id, values)
                customer_id = result.id
            elif action == "UPDATE":
                result = await self.repository.update_customer(
                    branch_id, customer_id, values
                )
            elif action == "DELETE":
                await self.repository.delete_customer(branch_id, customer_id)
                result = None
            else:
                raise ValueError("Unknown customer action")
            await self.audit.record(
                AuditRecord(
                    actor_user_id=actor,
                    branch_id=branch_id,
                    action="ADMIN_CUSTOMER_"
                    + {"CREATE": "CREATED", "UPDATE": "UPDATED", "DELETE": "DELETED"}[
                        action
                    ],
                    entity_type="CUSTOMER",
                    entity_id=customer_id,
                    before_state={"is_guest": before.is_guest} if before else None,
                    after_state={
                        "is_guest": result.is_guest,
                        **{f"changed_{key}": True for key in values},
                    }
                    if result
                    else None,
                )
            )
            await self.repository.commit()
            return result
        except Exception:
            await self.repository.rollback()
            raise
