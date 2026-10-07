from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.infrastructure.persistence.models import (
    CustomerAddressModel,
    CustomerModel,
)
from app.modules.orders.application.dtos import AddressSnapshot, CustomerSnapshot


class SQLAlchemyCustomerCheckoutGateway:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_customer(self, customer_id: UUID) -> CustomerSnapshot | None:
        row = (
            await self._session.execute(
                select(CustomerModel)
                .where(CustomerModel.id == customer_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return (
            CustomerSnapshot(id=row.id, full_name=row.full_name, phone=row.phone)
            if row
            else None
        )

    async def address(
        self, customer_id: UUID, address_id: UUID
    ) -> AddressSnapshot | None:
        row = (
            await self._session.execute(
                select(CustomerAddressModel)
                .where(
                    CustomerAddressModel.id == address_id,
                    CustomerAddressModel.customer_id == customer_id,
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return AddressSnapshot(
            **{
                name: getattr(row, name)
                for name in AddressSnapshot.__dataclass_fields__
            }
        )
