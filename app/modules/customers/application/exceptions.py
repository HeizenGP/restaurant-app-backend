from app.shared.application.exceptions import (
    ApplicationError,
    ConflictError,
    NotFoundError,
)


class CustomerNotFoundError(NotFoundError):
    code = "CUSTOMER_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Customer not found")


class AddressNotFoundError(NotFoundError):
    code = "ADDRESS_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Address not found")


class EmailAlreadyRegisteredError(ConflictError):
    code = "EMAIL_ALREADY_REGISTERED"

    def __init__(self) -> None:
        super().__init__("Email is already registered")


class InvalidCustomerDataError(ApplicationError):
    code = "INVALID_CUSTOMER_DATA"

    def __init__(self) -> None:
        super().__init__("Customer data is invalid")
