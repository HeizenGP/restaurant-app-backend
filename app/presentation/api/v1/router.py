from fastapi import APIRouter

from app.modules.auth.presentation.router import router as auth_router
from app.modules.branches.presentation.router import router as branches_router
from app.modules.customers.presentation.router import router as customers_router
from app.modules.health.presentation.router import router as health_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(customers_router)
router.include_router(branches_router)
