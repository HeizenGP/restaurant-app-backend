from app.shared.application.exceptions import (
    ConflictError,
    NotFoundError,
    RequestDataError,
)


class CartNotFoundError(NotFoundError):
    code = "CART_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Active cart not found")


class CartItemNotFoundError(NotFoundError):
    code = "CART_ITEM_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Cart item not found")


class ActiveCartExistsError(ConflictError):
    code = "ACTIVE_CART_EXISTS"

    def __init__(self) -> None:
        super().__init__("An active cart already exists")


class CartConflictError(ConflictError):
    code = "CART_CONFLICT"

    def __init__(self) -> None:
        super().__init__("Operation conflicts with current cart state")


class CartSelectionInvalidError(ConflictError):
    code = "CART_SELECTION_INVALID"

    def __init__(self) -> None:
        super().__init__("Product selection is no longer valid")


class CartProductUnavailableError(ConflictError):
    code = "CART_PRODUCT_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("Product is unavailable in the cart branch")


class CartRecalculationFailedError(ConflictError):
    code = "CART_RECALCULATION_FAILED"

    def __init__(self) -> None:
        super().__init__(
            "Cart contains an invalid selection; no snapshots were changed"
        )


class CartBranchInvalidError(ConflictError):
    code = "CART_BRANCH_INVALID"

    def __init__(self) -> None:
        super().__init__("Cart branch is not active or does not exist")


class InvalidCartDataError(RequestDataError):
    code = "INVALID_CART_DATA"

    def __init__(self) -> None:
        super().__init__("Invalid cart data")
