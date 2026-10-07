from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class CustomerBranchRecord:
    id: UUID
    timezone: str
    is_active: bool


class CustomerBranchReader(Protocol):
    async def customer_branch(
        self, branch_id: UUID, *, lock: bool = False
    ) -> CustomerBranchRecord | None: ...
