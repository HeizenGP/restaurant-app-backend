from app.shared.application.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
)


class BranchNotFoundError(NotFoundError):
    code = "BRANCH_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Branch not found")


class StaffForbiddenError(ForbiddenError):
    code = "FORBIDDEN"

    def __init__(self) -> None:
        super().__init__("You do not have permission for this branch")


class StaffUserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("User not found")


class StaffRoleNotFoundError(NotFoundError):
    code = "ROLE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Branch role not found")


class StaffAssignmentNotFoundError(NotFoundError):
    code = "STAFF_ASSIGNMENT_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("Staff assignment not found")


class StaffAssignmentExistsError(ConflictError):
    code = "STAFF_ASSIGNMENT_EXISTS"

    def __init__(self) -> None:
        super().__init__("Staff assignment already exists")
