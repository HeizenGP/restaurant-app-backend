"""Branches-owned read gateway, including the row barrier for customer operations."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.branches.application.customer_operations import CustomerBranchRecord


class SQLAlchemyCustomerBranchReader:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def customer_branch(self, branch_id, *, lock=False):
        rows = await self.session.execute(
            text(
                "SELECT id,timezone,(is_active AND deleted_at IS NULL) AS is_active "
                "FROM branches WHERE id=:id" + (" FOR SHARE" if lock else "")
            ),
            {"id": branch_id},
        )
        row = rows.mappings().one_or_none()
        return CustomerBranchRecord(**row) if row else None
