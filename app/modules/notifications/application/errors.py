from app.shared.application.exceptions import (
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
)


class NotificationNotFoundError(NotFoundError):
    code = "NOTIFICATION_NOT_FOUND"

    def __init__(self):
        super().__init__("Notification was not found")


class DeviceNotFoundError(NotFoundError):
    code = "NOTIFICATION_DEVICE_NOT_FOUND"

    def __init__(self):
        super().__init__("Device was not found")


class DeviceConflictError(ConflictError):
    code = "NOTIFICATION_DEVICE_CONFLICT"

    def __init__(self):
        super().__init__("Device registration conflicts with its current state")


class DeviceBusyError(ConflictError):
    code = "NOTIFICATION_DEVICE_BUSY"

    def __init__(self):
        super().__init__("Device has an active push lease; retry after it finishes")


class PushProviderUnavailableError(DependencyUnavailableError):
    code = "PUSH_PROVIDER_UNAVAILABLE"

    def __init__(self):
        super().__init__("Push provider is not configured or available")


class NotificationDataError(DependencyUnavailableError):
    code = "NOTIFICATION_DATA_UNAVAILABLE"

    def __init__(self):
        super().__init__("Notification persistence is unavailable or inconsistent")


class RealtimePermissionError(ForbiddenError):
    code = "ORDER_REALTIME_PERMISSION_DENIED"

    def __init__(self):
        super().__init__("Realtime permission is required for this branch")
