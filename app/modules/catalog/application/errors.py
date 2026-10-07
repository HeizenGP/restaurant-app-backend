from app.shared.application.exceptions import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
)


class CatalogNotFoundError(NotFoundError):
    def __init__(self, entity: str) -> None:
        self.code = f"{entity.upper()}_NOT_FOUND"
        super().__init__("Catalog resource not found")


class CatalogPermissionDeniedError(ForbiddenError):
    code = "CATALOG_PERMISSION_DENIED"

    def __init__(self) -> None:
        super().__init__("Catalog permission denied")


class CatalogConflictError(ConflictError):
    def __init__(self, code: str = "CATALOG_CONFLICT") -> None:
        self.code = code
        super().__init__("Operation conflicts with current catalog state")


class InvalidCatalogDataError(RequestDataError):
    code = "INVALID_CATALOG_DATA"

    def __init__(self) -> None:
        super().__init__("Invalid catalog configuration")


class InvalidSelectionError(ApplicationError):
    code = "INVALID_CATALOG_SELECTION"

    def __init__(self) -> None:
        super().__init__("Invalid product presentation, addons or notes")


class ProductNotAvailableError(ConflictError):
    code = "PRODUCT_NOT_AVAILABLE"

    def __init__(self) -> None:
        super().__init__("Product is sold out in this branch")
