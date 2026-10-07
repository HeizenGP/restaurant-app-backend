from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)


class SQLAlchemyCancellationAuthorization:
    def __init__(self, session):
        self.branches = SQLAlchemyBranchRepository(session)

    async def has_permission(self, user_id, branch_id, permission):
        return await self.branches.has_permission(user_id, branch_id, permission)
