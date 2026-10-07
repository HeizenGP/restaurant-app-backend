from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)


class SQLAlchemyNotificationAuthorization:
    def __init__(self, session):
        self.branches = SQLAlchemyBranchRepository(session)

    async def has_permission(self, user, branch, permission):
        return await self.branches.has_permission(user, branch, permission)
