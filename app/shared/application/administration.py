"""Branch-scoped administration contracts; no transport or ORM dependencies."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
)


@dataclass(frozen=True)
class AdministrativeBranch:
    id: UUID
    name: str
    timezone: str


class AdministrationAuthorization(Protocol):
    async def has_permission(
        self, user_id: UUID, branch_id: UUID, permission_code: str
    ) -> bool: ...
    async def authorized_branches(
        self, user_id: UUID, permission: str, *, branch_id: UUID | None = None
    ) -> tuple[AdministrativeBranch, ...]: ...

    async def has_any_permission(self, user_id: UUID, permission: str) -> bool: ...


class AdminPermissionDenied(ForbiddenError):
    code = "ADMIN_PERMISSION_DENIED"

    def __init__(self) -> None:
        super().__init__("You do not have permission for this branch")


class AdministrationConflict(ConflictError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AdministrationNotFound(NotFoundError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AdministrationInvalid(RequestDataError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def administrative_actor(principal: Principal) -> UUID:
    if (
        principal.principal_type is not PrincipalType.REGISTERED
        or principal.user_id is None
    ):
        raise AdminPermissionDenied()
    return principal.user_id


async def require_administration(
    auth: AdministrationAuthorization,
    principal: Principal,
    branch_id: UUID,
    permission: str,
) -> UUID:
    actor = administrative_actor(principal)
    if not await auth.has_permission(actor, branch_id, permission):
        raise AdminPermissionDenied()
    return actor
