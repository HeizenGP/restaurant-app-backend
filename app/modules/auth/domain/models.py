from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    DISABLED = "DISABLED"


class RoleScope(StrEnum):
    GLOBAL = "GLOBAL"
    BRANCH = "BRANCH"


class OtpPurpose(StrEnum):
    GUEST_ACCESS = "GUEST_ACCESS"
    REGISTER = "REGISTER"
    LOGIN = "LOGIN"
    PHONE_VERIFY = "PHONE_VERIFY"


class PrincipalType(StrEnum):
    REGISTERED = "registered"
    GUEST = "guest"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    PHONE_VERIFICATION = "phone_verification"


@dataclass(frozen=True, slots=True, kw_only=True)
class Principal:
    """Authenticated identity without transport- or persistence-specific details."""

    principal_type: PrincipalType
    user_id: UUID | None = None
    customer_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.principal_type is PrincipalType.REGISTERED:
            if self.user_id is None:
                raise ValueError("A registered principal requires a user_id")
            return

        if self.customer_id is None:
            raise ValueError("A guest principal requires a customer_id")
        if self.user_id is not None:
            raise ValueError("A guest principal cannot have a user_id")
