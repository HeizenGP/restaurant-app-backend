from app.shared.application.exceptions import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
)


class FulfillmentConflictError(ConflictError):
    def __init__(self, code: str = "FULFILLMENT_INVALID_TRANSITION"):
        self.code = code
        super().__init__("Fulfillment action conflicts with the current state")


class FulfillmentNotFoundError(NotFoundError):
    def __init__(self, *, incident: bool = False):
        self.code = (
            "DELIVERY_DELAY_NOT_FOUND" if incident else "FULFILLMENT_ORDER_NOT_FOUND"
        )
        super().__init__("Fulfillment resource was not found")


class FulfillmentPermissionDeniedError(ForbiddenError):
    code = "FULFILLMENT_PERMISSION_DENIED"

    def __init__(self):
        super().__init__("Fulfillment permission is required for this branch")


class FulfillmentDataError(DependencyUnavailableError):
    code = "FULFILLMENT_DATA_INCONSISTENT"

    def __init__(self):
        super().__init__("Fulfillment data is inconsistent")
