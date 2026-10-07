from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

AuditValue = str | int | bool | None
AuditState = dict[str, AuditValue]


@dataclass(frozen=True, kw_only=True)
class AuditRecord:
    actor_user_id: UUID
    branch_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID
    before_state: AuditState | None
    after_state: AuditState | None


class AuditRecorder(Protocol):
    async def record(self, event: AuditRecord) -> None: ...
