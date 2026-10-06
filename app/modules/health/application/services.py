from dataclasses import dataclass

from app.modules.health.application.ports import DatabaseProbe
from app.shared.application.exceptions import DependencyUnavailableError


@dataclass(frozen=True)
class HealthStatus:
    status: str
    service: str
    version: str


@dataclass(frozen=True)
class ReadinessStatus:
    status: str
    database: str


class HealthService:
    def __init__(self, service: str, version: str, database: DatabaseProbe) -> None:
        self._service = service
        self._version = version
        self._database = database

    def liveness(self) -> HealthStatus:
        return HealthStatus(status="ok", service=self._service, version=self._version)

    async def readiness(self) -> ReadinessStatus:
        if not await self._database.is_ready():
            raise DependencyUnavailableError("Database is unavailable")
        return ReadinessStatus(status="ready", database="connected")
