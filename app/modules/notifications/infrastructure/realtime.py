"""Each poll owns a short session, closed before yielding or sleeping."""

from sqlalchemy.exc import SQLAlchemyError

from app.modules.auth.domain.models import PrincipalType
from app.modules.notifications.application.dtos import StreamBatch
from app.modules.notifications.application.errors import (
    NotificationDataError,
    RealtimePermissionError,
)
from app.modules.notifications.infrastructure.authorization import (
    SQLAlchemyNotificationAuthorization,
)
from app.modules.notifications.infrastructure.persistence.repositories import (
    SQLAlchemyNotificationRepository,
)
from app.shared.application.exceptions import UnauthorizedError


class SQLAlchemyStreamReader:
    def __init__(self, session_factory, resolve_identity, decode_claims):
        self.factory, self.resolve_identity, self.decode_claims = (
            session_factory,
            resolve_identity,
            decode_claims,
        )

    async def read(self, scope, after, limit, *, revalidate):
        try:
            async with self.factory() as session:
                expires = None
                if revalidate:
                    identity = await self.resolve_identity(session, scope.credential)
                    claims = self.decode_claims(scope.credential)
                    if identity != scope.principal:
                        raise UnauthorizedError("Stream identity changed")
                    expires = claims.expires_at
                    if scope.branch_id is not None:
                        if (
                            identity.principal_type != PrincipalType.REGISTERED
                            or identity.user_id is None
                            or not await SQLAlchemyNotificationAuthorization(
                                session
                            ).has_permission(
                                identity.user_id, scope.branch_id, scope.permission
                            )
                        ):
                            raise RealtimePermissionError()
                repo = SQLAlchemyNotificationRepository(session)
                watermark = await repo.high_watermark(
                    customer=scope.principal.customer_id
                    if scope.branch_id is None
                    else None,
                    branch=scope.branch_id,
                )
                items = ()
                if after is not None:
                    items = (
                        tuple(
                            await repo.stream_notifications(
                                scope.principal.customer_id, after, watermark, limit
                            )
                        )
                        if scope.branch_id is None
                        else tuple(
                            await repo.events(scope.branch_id, after, limit, watermark)
                        )
                    )
                return StreamBatch(items=items, latest_id=watermark, expires_at=expires)
                # __aexit__ rolls back the read transaction/releases connection.
        except (SQLAlchemyError, OSError, TimeoutError):
            raise NotificationDataError() from None
