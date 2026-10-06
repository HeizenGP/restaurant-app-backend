from fastapi import Request

from app.modules.health.application.services import HealthService


def get_health_service(request: Request) -> HealthService:
    return request.app.state.health_service
