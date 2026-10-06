from fastapi import APIRouter

from app.modules.health.presentation.router import HealthServiceDependency
from app.presentation.api.v1.router import router as v1_router

legacy_router = APIRouter()


@legacy_router.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"message": "Restaurante API", "status": "running"}


@legacy_router.get("/health", include_in_schema=False)
async def legacy_health(service: HealthServiceDependency) -> dict[str, str]:
    return {"status": service.liveness().status}


def create_api_router(api_v1_prefix: str) -> APIRouter:
    router = APIRouter()
    router.include_router(legacy_router)
    router.include_router(v1_router, prefix=api_v1_prefix)
    return router
