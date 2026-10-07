from app.shared.application.exceptions import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
)


class KitchenPermissionDeniedError(ForbiddenError):
    code = "KITCHEN_PERMISSION_DENIED"

    def __init__(self) -> None:
        super().__init__("Kitchen permission is required for this branch")


class KitchenOrderNotFoundError(NotFoundError):
    code = "KITCHEN_ORDER_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Kitchen order was not found")


class KitchenInvalidTransitionError(ConflictError):
    code = "KITCHEN_INVALID_TRANSITION"

    def __init__(self) -> None:
        super().__init__("Kitchen operation conflicts with the current order state")


class KitchenOrderNotConfirmedError(ConflictError):
    code = "KITCHEN_ORDER_NOT_CONFIRMED"

    def __init__(self) -> None:
        super().__init__("Order is not confirmed for preparation")


class KitchenIntegrityError(DependencyUnavailableError):
    code = "KITCHEN_HISTORY_INCONSISTENT"

    def __init__(self) -> None:
        super().__init__("Operational order data is inconsistent")
