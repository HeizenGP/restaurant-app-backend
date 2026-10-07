"""Identity/key validation shared by customer use cases, not a business slice."""

import hashlib
import re
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.shared.application.exceptions import (
    ForbiddenError,
    RequestDataError,
    UnauthorizedError,
)


class RegisteredAccountRequired(ForbiddenError):
    code = "REGISTERED_ACCOUNT_REQUIRED"

    def __init__(self):
        super().__init__("A registered account is required")


def account_identity(principal: Principal) -> UUID:
    if (
        principal.principal_type != PrincipalType.REGISTERED
        or principal.user_id is None
    ):
        raise RegisteredAccountRequired()
    return principal.user_id


def customer_identity(principal: Principal) -> UUID:
    if principal.customer_id is None:
        raise UnauthorizedError("Customer identity is required")
    return principal.customer_id


def idempotency_digest(key: str) -> str:
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key):
        raise RequestDataError("Invalid Idempotency-Key")
    return hashlib.sha256(key.encode()).hexdigest()
