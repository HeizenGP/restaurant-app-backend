from app.shared.application.exceptions import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)


class RefundConflictError(ConflictError):
    def __init__(self, code="REFUND_INVALID_STATE"):
        self.code = code
        super().__init__("Refund action conflicts with the current state")


class RefundDataError(DependencyUnavailableError):
    code = "REFUND_REQUIRED_PAYMENT_MISSING"

    def __init__(self):
        super().__init__("Refund financial evidence is inconsistent or unavailable")


class RefundProviderUnavailableError(DependencyUnavailableError):
    code = "REFUND_PROVIDER_UNAVAILABLE"

    def __init__(self):
        super().__init__("Online refund provider is unavailable")


class RefundEventPendingError(DependencyUnavailableError):
    code = "REFUND_PROVIDER_EVENT_PENDING"

    def __init__(self):
        super().__init__("Verified refund event awaits correlation")


class RefundPermissionDeniedError(ForbiddenError):
    code = "REFUND_PERMISSION_DENIED"

    def __init__(self):
        super().__init__("Refund permission is required for this branch")


class RefundNotFoundError(NotFoundError):
    code = "REFUND_NOT_FOUND"

    def __init__(self):
        super().__init__("Refund was not found")


class RefundWebhookAuthenticationError(UnauthorizedError):
    code = "REFUND_PROVIDER_EVENT_INVALID"

    def __init__(self):
        super().__init__("Refund webhook authentication failed")
