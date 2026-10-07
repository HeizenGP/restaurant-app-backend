from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.application.audit import AuditRecord
from app.shared.infrastructure.audit.models import AuditLogModel


class SQLAlchemyAuditRecorder:
    """Adds an event to the caller's session; never commits independently."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, event: AuditRecord) -> None:
        self._session.add(
            AuditLogModel(
                actor_user_id=event.actor_user_id,
                branch_id=event.branch_id,
                action=event.action,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                before_state=event.before_state,
                after_state=event.after_state,
            )
        )
