from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.health.application.services import (
    HealthService,
    HealthStatus,
    ReadinessStatus,
)
from app.modules.health.presentation.dependencies import get_health_service
from app.modules.health.presentation.schemas import HealthResponse, ReadinessResponse
from app.presentation.errors import ErrorResponse

router = APIRouter(prefix="/health", tags=["health"])
HealthServiceDependency = Annotated[HealthService, Depends(get_health_service)]


@router.get("", response_model=HealthResponse)
async def health(service: HealthServiceDependency) -> HealthStatus:
    return service.liveness()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ErrorResponse}},
)
async def readiness(service: HealthServiceDependency) -> ReadinessStatus:
    return await service.readiness()
