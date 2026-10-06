from fastapi import APIRouter, Response, status

from app.modules.auth.presentation.dependencies import (
    AuthServiceDependency,
    CurrentRegisteredUser,
)
from app.modules.auth.presentation.schemas import (
    GuestRequest,
    GuestTokenResponse,
    LoginRequest,
    LogoutRequest,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    PasswordChangeRequest,
    PhoneChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
)
from app.presentation.errors import ErrorResponse

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    responses={
        code: {"model": ErrorResponse} for code in (400, 401, 403, 409, 422, 429, 503)
    },
)


@router.post(
    "/otp/request",
    response_model=OtpRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    response_model_exclude_none=True,
)
async def request_otp(
    body: OtpRequest, service: AuthServiceDependency
) -> OtpRequestResponse:
    result = await service.request_otp(body.phone, body.purpose)
    return OtpRequestResponse(accepted=True, debug_code=result.debug_code)


@router.post("/otp/verify", response_model=OtpVerifyResponse)
async def verify_otp(
    body: OtpVerifyRequest, service: AuthServiceDependency
) -> OtpVerifyResponse:
    token = await service.verify_otp(body.phone, body.purpose, body.code)
    return OtpVerifyResponse(verification_token=token)


@router.post(
    "/register",
    response_model=TokenPairResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest, service: AuthServiceDependency
) -> TokenPairResponse:
    result = await service.register(
        verification_token=body.verification_token,
        first_name=body.first_name,
        last_name=body.last_name,
        email=str(body.email) if body.email is not None else None,
        password=body.password.get_secret_value(),
    )
    return TokenPairResponse.model_validate(result)


@router.post("/guest", response_model=GuestTokenResponse)
async def guest(
    body: GuestRequest, service: AuthServiceDependency
) -> GuestTokenResponse:
    result = await service.create_guest(
        verification_token=body.verification_token,
        full_name=body.full_name,
    )
    return GuestTokenResponse.model_validate(result)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    body: LoginRequest, service: AuthServiceDependency
) -> TokenPairResponse:
    result = await service.login(body.identifier, body.password.get_secret_value())
    return TokenPairResponse.model_validate(result)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    body: RefreshRequest, service: AuthServiceDependency
) -> TokenPairResponse:
    result = await service.refresh(body.refresh_token.get_secret_value())
    return TokenPairResponse.model_validate(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, service: AuthServiceDependency) -> Response:
    await service.logout(body.refresh_token.get_secret_value())
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest,
    principal: CurrentRegisteredUser,
    service: AuthServiceDependency,
) -> Response:
    await service.change_password(
        principal,
        body.current_password.get_secret_value(),
        body.new_password.get_secret_value(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/phone/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_phone(
    body: PhoneChangeRequest,
    principal: CurrentRegisteredUser,
    service: AuthServiceDependency,
) -> Response:
    await service.change_phone(principal, body.verification_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
