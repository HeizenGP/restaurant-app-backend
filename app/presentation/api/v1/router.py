from fastapi import APIRouter

from app.modules.auth.presentation.router import router as auth_router
from app.modules.branches.presentation.router import router as branches_router
from app.modules.cancellations.presentation.router import (
    admin_router as admin_cancellations_router,
)
from app.modules.cancellations.presentation.router import (
    router as cancellations_router,
)
from app.modules.cart.presentation.router import router as cart_router
from app.modules.catalog.presentation.router import admin_router as admin_catalog_router
from app.modules.catalog.presentation.router import router as catalog_router
from app.modules.customers.presentation.router import router as customers_router
from app.modules.fulfillment.presentation.router import router as fulfillment_router
from app.modules.health.presentation.router import router as health_router
from app.modules.kitchen.presentation.router import router as kitchen_router
from app.modules.notifications.presentation.router import (
    admin_router as admin_realtime_router,
)
from app.modules.notifications.presentation.router import (
    kitchen_router as kitchen_realtime_router,
)
from app.modules.notifications.presentation.router import (
    router as notifications_router,
)
from app.modules.orders.presentation.router import admin_router as admin_orders_router
from app.modules.orders.presentation.router import router as orders_router
from app.modules.payments.presentation.refund_router import (
    admin_router as admin_refunds_router,
)
from app.modules.payments.presentation.refund_router import (
    router as refunds_router,
)
from app.modules.payments.presentation.router import (
    admin_router as admin_payments_router,
)
from app.modules.payments.presentation.router import router as payments_router

router = APIRouter()
router.include_router(health_router)
router.include_router(auth_router)
router.include_router(customers_router)
router.include_router(branches_router)
router.include_router(catalog_router)
router.include_router(admin_catalog_router)
router.include_router(cart_router)
router.include_router(orders_router)
router.include_router(admin_orders_router)
router.include_router(kitchen_realtime_router)
router.include_router(kitchen_router)
router.include_router(payments_router)
router.include_router(admin_payments_router)
router.include_router(fulfillment_router)
router.include_router(cancellations_router)
router.include_router(admin_cancellations_router)
router.include_router(refunds_router)
router.include_router(admin_refunds_router)
router.include_router(notifications_router)
router.include_router(admin_realtime_router)
