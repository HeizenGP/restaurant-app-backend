from collections.abc import Sequence
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from app.modules.customers.application.dtos import (
    Address,
    AddressCreate,
    AddressUpdate,
    CustomerProfile,
    ProfileUpdate,
)


class CustomerRepository(Protocol):
    async def get_profile(
        self, customer_id: UUID, *, user_id: UUID | None
    ) -> CustomerProfile | None: ...

    async def email_is_registered(self, email: str, *, excluding: UUID) -> bool: ...

    async def update_guest_profile(
        self, customer_id: UUID, *, full_name: str
    ) -> CustomerProfile | None: ...

    async def update_registered_profile(
        self,
        customer_id: UUID,
        user_id: UUID,
        update: ProfileUpdate,
    ) -> CustomerProfile | None: ...

    async def list_addresses(self, customer_id: UUID) -> Sequence[Address]: ...

    async def create_address(
        self, customer_id: UUID, address: AddressCreate
    ) -> Address: ...

    async def update_address(
        self, customer_id: UUID, address_id: UUID, update: AddressUpdate
    ) -> Address | None: ...

    async def delete_address(self, customer_id: UUID, address_id: UUID) -> bool: ...

    async def unset_default_address(
        self, customer_id: UUID, *, keeping: UUID | None = None
    ) -> None: ...


class CustomerUnitOfWork(Protocol):
    customers: CustomerRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class CustomerUnitOfWorkFactory(Protocol):
    def __call__(self) -> CustomerUnitOfWork: ...
