import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlmodel import SQLModel

from app.modules.auth.infrastructure.persistence import models as auth_models
from app.modules.branches.infrastructure.persistence import models as branch_models
from app.modules.cancellations.infrastructure.persistence import (
    models as cancellation_models,
)
from app.modules.cart.infrastructure.persistence import models as cart_models
from app.modules.catalog.infrastructure.persistence import models as catalog_models
from app.modules.customers.infrastructure.persistence import models as customer_models
from app.modules.favorites.infrastructure.persistence import models as favorite_models
from app.modules.fulfillment.infrastructure.persistence import (
    models as fulfillment_models,
)
from app.modules.notifications.infrastructure.persistence import (
    models as notification_models,
)
from app.modules.orders.infrastructure.persistence import models as order_models
from app.modules.payments.infrastructure.persistence import models as payment_models
from app.modules.payments.infrastructure.persistence import (
    refund_models,
)
from app.modules.promotions.infrastructure.persistence import models as promotion_models
from app.modules.receipts.infrastructure.persistence import models as receipt_models
from app.modules.reviews.infrastructure.persistence import models as review_models
from app.shared.infrastructure.audit import models as audit_models
from app.shared.infrastructure.config.settings import get_settings
from app.shared.infrastructure.database.engine import create_database_engine
from app.shared.infrastructure.logging.config import configure_logging

# Referencing the modules documents and preserves the imports that register every
# persistence table on SQLModel.metadata before Alembic inspects it.
_PERSISTENCE_MODEL_MODULES = (
    auth_models,
    branch_models,
    customer_models,
    catalog_models,
    cart_models,
    order_models,
    payment_models,
    cancellation_models,
    refund_models,
    fulfillment_models,
    notification_models,
    audit_models,
    favorite_models,
    review_models,
    receipt_models,
    promotion_models,
)
target_metadata = SQLModel.metadata
settings = get_settings()
configure_logging(settings)


def include_name(name: str | None, type_: str, parent_names: dict[str, str]) -> bool:
    if type_ == "table":
        # Existing tables outside SQLModel's ownership must never be dropped by
        # autogenerate while the restaurant schema is adopted slice by slice.
        return parent_names["schema_qualified_table_name"] in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_connection_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_database_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif context.config.attributes.get("connection") is not None:
    # An explicit caller-owned connection lets isolated migration tests roll back
    # all DDL without connecting to the configured development database.
    do_run_migrations(context.config.attributes["connection"])
else:
    asyncio.run(run_migrations_online())
