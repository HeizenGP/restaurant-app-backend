from app.shared.application.exceptions import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
    UnauthorizedError,
)


class PaymentConflictError(ConflictError):
    def __init__(self, code: str = "PAYMENT_INVALID_STATE") -> None:
        self.code = code
        super().__init__("Payment operation conflicts with the current state")


class PaymentNotFoundError(NotFoundError):
    def __init__(self, *, order: bool = False) -> None:
        self.code = "PAYMENT_ORDER_NOT_FOUND" if order else "PAYMENT_NOT_FOUND"
        super().__init__("Payment resource was not found")


class PaymentCashPermissionDeniedError(ForbiddenError):
    code = "PAYMENT_CASH_PERMISSION_DENIED"

    def __init__(self) -> None:
        super().__init__("Cash payment permission is required for this branch")


class PaymentProviderUnavailableError(DependencyUnavailableError):
    code = "PAYMENT_PROVIDER_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("Online payment provider is unavailable")


class PaymentDataError(DependencyUnavailableError):
    code = "PAYMENT_DATA_INCONSISTENT"

    def __init__(self) -> None:
        super().__init__("Payment data is inconsistent")


class PaymentWebhookAuthenticationError(UnauthorizedError):
    code = "PAYMENT_PROVIDER_EVENT_INVALID"

    def __init__(self) -> None:
        super().__init__("Provider event could not be authenticated")


class PaymentEventInvalidError(RequestDataError):
    code = "PAYMENT_PROVIDER_EVENT_INVALID"

    def __init__(self) -> None:
        super().__init__("Invalid provider event")


class PaymentEventPendingError(DependencyUnavailableError):
    code = "PAYMENT_PROVIDER_EVENT_PENDING"

    def __init__(self) -> None:
        super().__init__("Provider event is awaiting payment correlation")


class PaymentProviderDeclinedError(ConflictError):
    code = "PAYMENT_DECLINED"

    def __init__(self) -> None:
        super().__init__("Provider declined this payment attempt")
