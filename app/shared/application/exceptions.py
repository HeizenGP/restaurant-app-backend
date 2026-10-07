class ApplicationError(Exception):
    """An expected use-case failure with a client-safe message."""

    code = "APPLICATION_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class UnauthorizedError(ApplicationError):
    """Authentication is missing or is no longer valid."""

    code = "AUTHENTICATION_REQUIRED"


class RequestDataError(ApplicationError):
    """Input violates a rule that needs current persisted context."""

    code = "INVALID_REQUEST_DATA"


class ForbiddenError(ApplicationError):
    """The authenticated principal cannot perform the operation."""

    code = "FORBIDDEN"


class NotFoundError(ApplicationError):
    """The requested aggregate does not exist or is not visible."""

    code = "NOT_FOUND"


class ConflictError(ApplicationError):
    """The operation conflicts with current persisted state."""

    code = "CONFLICT"


class TooManyRequestsError(ApplicationError):
    """A safety throttle rejected the operation."""

    code = "TOO_MANY_REQUESTS"


class DependencyUnavailableError(ApplicationError):
    """A use case cannot run because a required dependency is unavailable."""

    code = "DEPENDENCY_UNAVAILABLE"
