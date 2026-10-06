class SecurityPrimitiveError(ValueError):
    """Base error for a rejected security primitive operation."""


class TokenValidationError(SecurityPrimitiveError):
    """A token cannot be trusted or does not satisfy its contract."""


class TokenInvalidError(TokenValidationError):
    """A token is malformed, has invalid claims, or has an invalid signature."""


class TokenExpiredError(TokenValidationError):
    """A token is otherwise valid but has expired."""


class TokenTypeMismatchError(TokenInvalidError):
    """A valid token was presented for a different token purpose."""
