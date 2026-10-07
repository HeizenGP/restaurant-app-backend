from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class AdministrativeCustomer:
    id: UUID
    full_name: str
    phone: str
    email: str | None
    is_guest: bool
    phone_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    first_name: str | None = None
    last_name: str | None = None


class CustomerAdministrationRepository(Protocol):
    async def list_customers(
        self, branch_id: UUID, search: str | None, limit: int, offset: int
    ) -> list[AdministrativeCustomer]: ...
    async def get_customer(
        self, branch_id: UUID, customer_id: UUID, *, lock: bool = False
    ) -> AdministrativeCustomer | None: ...
    async def create_customer(
        self, branch_id: UUID, values: dict
    ) -> AdministrativeCustomer: ...
    async def update_customer(
        self, branch_id: UUID, customer_id: UUID, values: dict
    ) -> AdministrativeCustomer: ...
    async def delete_customer(self, branch_id: UUID, customer_id: UUID) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
