"""Public Orders-owned read gateway; does not mutate Orders or Payments."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.application.customer_records import CustomerOrderRecord


class SQLAlchemyCustomerOrderReader:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def customer_order(
        self, customer_id: UUID, order_id: UUID, *, lock: bool = False
    ):
        result = await self.session.execute(
            text(
                "SELECT o.id,o.customer_id,o.branch_id,o.mode,o.status,"
                "o.payment_status,"
                "o.total,p.amount AS paid_amount,p.status AS ledger_status "
                "FROM orders o LEFT JOIN payments p ON p.order_id=o.id "
                "WHERE o.id=:order AND o.customer_id=:customer"
                + (" FOR UPDATE OF o" if lock else "")
            ),
            {"order": order_id, "customer": customer_id},
        )
        row = result.mappings().one_or_none()
        return CustomerOrderRecord(**row) if row else None
