from fastapi import APIRouter

from app.modules.health.presentation.router import router as health_router

router = APIRouter()
router.include_router(health_router)
