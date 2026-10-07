from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
)


class OrderNotFoundError(NotFoundError):
    code = "ORDER_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Order was not found")


class OrderConflictError(ConflictError):
    def __init__(self, code: str = "ORDER_CONFLICT") -> None:
        self.code = code
        super().__init__("Order operation conflicts with current state")


class OrderResourceNotFoundError(NotFoundError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("Order resource was not found")


class OrderPermissionDeniedError(ForbiddenError):
    def __init__(self, permission: str) -> None:
        self.code = (
            "ORDER_SETTINGS_PERMISSION_DENIED"
            if permission == "ORDER_SETTINGS_MANAGE"
            else "ORDER_PERMISSION_DENIED"
        )
        super().__init__("Order permission is required for this branch")


class InvalidOrderDataError(RequestDataError):
    code = "INVALID_ORDER_DATA"

    def __init__(self) -> None:
        super().__init__("Invalid order data")


class OrderUniqueConflictError(OrderConflictError):
    """Safe infrastructure signal used to resolve the database race barrier."""

    def __init__(self, constraint: str | None) -> None:
        self.constraint = constraint
        super().__init__("ORDER_ALREADY_CREATED")
