import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.shared.application.exceptions import (
    ApplicationError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    RequestDataError,
    TooManyRequestsError,
    UnauthorizedError,
)
from app.shared.domain.exceptions import DomainError

logger = logging.getLogger(__name__)


class ValidationIssue(BaseModel):
    location: list[str | int]
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[ValidationIssue] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[ValidationIssue] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return error_response(409, exc.code, exc.message)


async def application_error_handler(
    request: Request, exc: ApplicationError
) -> JSONResponse:
    status_code = 400
    headers = None
    if isinstance(exc, UnauthorizedError):
        status_code = 401
        headers = {"WWW-Authenticate": "Bearer"}
    elif isinstance(exc, ForbiddenError):
        status_code = 403
    elif isinstance(exc, NotFoundError):
        status_code = 404
    elif isinstance(exc, ConflictError):
        status_code = 409
    elif isinstance(exc, TooManyRequestsError):
        status_code = 429
    elif isinstance(exc, RequestDataError):
        status_code = 422
    elif isinstance(exc, DependencyUnavailableError):
        status_code = 503
    return error_response(status_code, exc.code, exc.message, headers=headers)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed"
    return error_response(exc.status_code, "HTTP_ERROR", message, headers=exc.headers)


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Return locations/types, never the rejected input or validator context.
    details = [
        ValidationIssue(location=list(issue["loc"]), type=issue["type"])
        for issue in exc.errors()
    ]
    return error_response(
        422, "VALIDATION_ERROR", "Request validation failed", details=details
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    frames = traceback.extract_tb(exc.__traceback__)
    locations = " -> ".join(
        f"{frame.filename}:{frame.lineno} ({frame.name})" for frame in frames
    )
    # Keep diagnostic locations without logging exception values or request secrets.
    logger.error("Unhandled %s at %s", type(exc).__name__, locations)
    response = error_response(
        500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred"
    )
    # ServerErrorMiddleware is outside CORSMiddleware. Preserve allowed-origin
    # headers for this response without changing the application factory contract.
    origin = request.headers.get("origin")
    settings = getattr(request.app.state, "settings", None)
    if origin is not None and settings is not None and origin in settings.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(DomainError, domain_error_handler)
    application.add_exception_handler(ApplicationError, application_error_handler)
    application.add_exception_handler(HTTPException, http_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)
