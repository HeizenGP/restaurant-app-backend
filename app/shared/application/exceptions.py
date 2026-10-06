class ApplicationError(Exception):
    """An expected use-case failure with a client-safe message."""

    code = "APPLICATION_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DependencyUnavailableError(ApplicationError):
    """A use case cannot run because a required dependency is unavailable."""

    code = "DEPENDENCY_UNAVAILABLE"
