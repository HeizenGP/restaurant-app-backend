class DomainError(Exception):
    """An expected business rule violation with a client-safe message."""

    code = "DOMAIN_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
