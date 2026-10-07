from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class CustomerOrderRecord:
    id: UUID
    customer_id: UUID
    branch_id: UUID
    mode: str
    status: str
    payment_status: str
    total: Decimal
    paid_amount: Decimal | None
    ledger_status: str | None


class CustomerOrderReader(Protocol):
    async def customer_order(
        self, customer_id: UUID, order_id: UUID, *, lock: bool = False
    ) -> CustomerOrderRecord | None: ...
