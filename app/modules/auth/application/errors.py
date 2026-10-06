from app.shared.application.exceptions import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    TooManyRequestsError,
    UnauthorizedError,
)


class InvalidCredentialsError(UnauthorizedError):
    code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__("Invalid credentials")


class TokenInvalidApplicationError(UnauthorizedError):
    code = "TOKEN_INVALID"

    def __init__(self) -> None:
        super().__init__("Token is invalid")


class TokenExpiredApplicationError(UnauthorizedError):
    code = "TOKEN_EXPIRED"

    def __init__(self) -> None:
        super().__init__("Token has expired")


class RefreshTokenRevokedError(UnauthorizedError):
    code = "REFRESH_TOKEN_REVOKED"

    def __init__(self) -> None:
        super().__init__("Refresh token is no longer valid")


class AccountBlockedError(ForbiddenError):
    code = "ACCOUNT_BLOCKED"

    def __init__(self) -> None:
        super().__init__("Account is blocked")


class AccountDisabledError(ForbiddenError):
    code = "ACCOUNT_DISABLED"

    def __init__(self) -> None:
        super().__init__("Account is disabled")


class RegisteredUserRequiredError(ForbiddenError):
    code = "REGISTERED_USER_REQUIRED"

    def __init__(self) -> None:
        super().__init__("A registered account is required")


class PhoneAlreadyRegisteredError(ConflictError):
    code = "PHONE_ALREADY_REGISTERED"

    def __init__(self) -> None:
        super().__init__("Phone is already registered")


class EmailAlreadyRegisteredError(ConflictError):
    code = "EMAIL_ALREADY_REGISTERED"

    def __init__(self) -> None:
        super().__init__("Email is already registered")


class IdentityConflictError(ConflictError):
    code = "IDENTITY_CONFLICT"

    def __init__(self) -> None:
        super().__init__("Identity data conflicts with an existing account")


class RegisteredCustomerLoginRequiredError(ConflictError):
    code = "REGISTERED_CUSTOMER_LOGIN_REQUIRED"

    def __init__(self) -> None:
        super().__init__("Sign in with the registered account")


class InvalidPasswordError(ConflictError):
    code = "INVALID_PASSWORD"

    def __init__(self) -> None:
        super().__init__("Password must contain between 8 and 128 characters")


class CurrentPasswordInvalidError(UnauthorizedError):
    code = "INVALID_CREDENTIALS"

    def __init__(self) -> None:
        super().__init__("Invalid credentials")


class OtpInvalidError(UnauthorizedError):
    code = "OTP_INVALID"

    def __init__(self) -> None:
        super().__init__("OTP is invalid")


class OtpExpiredError(UnauthorizedError):
    code = "OTP_EXPIRED"

    def __init__(self) -> None:
        super().__init__("OTP has expired")


class OtpAttemptsExceededError(TooManyRequestsError):
    code = "OTP_ATTEMPTS_EXCEEDED"

    def __init__(self) -> None:
        super().__init__("OTP attempt limit exceeded")


class OtpCooldownError(TooManyRequestsError):
    code = "OTP_COOLDOWN"

    def __init__(self) -> None:
        super().__init__("Wait before requesting another OTP")


class OtpDeliveryUnavailableError(DependencyUnavailableError):
    code = "OTP_DELIVERY_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("OTP delivery is not configured")


class AuthDataUnavailableError(UnauthorizedError):
    code = "AUTHENTICATION_REQUIRED"

    def __init__(self) -> None:
        super().__init__("Authentication is required")
