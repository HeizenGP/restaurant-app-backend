from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
)


class CancellationConflictError(ConflictError):
    def __init__(self, code="ORDER_NOT_CANCELLABLE"):
        self.code = code
        super().__init__("Cancellation conflicts with the current state")


class CancellationNotFoundError(NotFoundError):
    def __init__(self, code="CANCELLATION_REQUEST_NOT_FOUND"):
        self.code = code
        super().__init__("Cancellation resource was not found")


class CancellationPermissionDeniedError(ForbiddenError):
    code = "CANCELLATION_PERMISSION_DENIED"

    def __init__(self):
        super().__init__("Cancellation permission is required for this branch")
