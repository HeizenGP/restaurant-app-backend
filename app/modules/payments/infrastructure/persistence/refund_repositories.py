from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.orders.infrastructure.persistence.models import OrderModel
from app.modules.payments.application.refund_dtos import (
    RefundAttemptLocator,
    RefundView,
)
from app.modules.payments.application.refund_errors import (
    RefundConflictError,
    RefundDataError,
)
from app.modules.payments.domain.models import (
    AttemptStatus,
    EventStatus,
    PaymentStatus,
    VerifiedResult,
)
from app.modules.payments.domain.refunds import (
    Refund,
    RefundAttempt,
    RefundHistorySource,
    RefundProviderEvent,
    RefundStatus,
    RefundStatusHistory,
)
from app.modules.payments.infrastructure.persistence.models import (
    PaymentAttemptModel,
    PaymentModel,
)
from app.modules.payments.infrastructure.persistence.refund_models import (
    RefundAttemptModel,
    RefundModel,
    RefundProviderEventModel,
    RefundStatusHistoryModel,
)
from app.modules.payments.infrastructure.persistence.repositories import attempt_domain


def refund_domain(row):
    try:
        return Refund(
            **(
                row.model_dump()
                | {
                    "status": RefundStatus(row.status),
                    "method_type": PaymentMethodType(row.method_type),
                }
            )
        )
    except (ValueError, TypeError):
        raise RefundDataError() from None


def refund_attempt_domain(row):
    try:
        return RefundAttempt(
            **(row.model_dump() | {"status": AttemptStatus(row.status)})
        )
    except (ValueError, TypeError):
        raise RefundDataError() from None


def refund_event_domain(row):
    try:
        return RefundProviderEvent(
            **(
                row.model_dump()
                | {
                    "result": VerifiedResult(row.result),
                    "processing_status": EventStatus(row.processing_status),
                }
            )
        )
    except (ValueError, TypeError):
        raise RefundDataError() from None


def refund_history_domain(row):
    try:
        return RefundStatusHistory(
            **(
                row.model_dump()
                | {
                    "from_status": RefundStatus(row.from_status)
                    if row.from_status
                    else None,
                    "to_status": RefundStatus(row.to_status),
                    "source": RefundHistorySource(row.source),
                }
            )
        )
    except (ValueError, TypeError):
        raise RefundDataError() from None


class SQLAlchemyRefundRepository:
    def __init__(self, session):
        self.session = session

    async def _execute(self, query):
        try:
            return await self.session.execute(query)
        except IntegrityError:
            raise RefundConflictError("REFUND_IDEMPOTENCY_CONFLICT") from None

    async def _insert(self, model):
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError:
            raise RefundConflictError("REFUND_IDEMPOTENCY_CONFLICT") from None

    async def _refund(self, query, lock=False):
        if lock:
            query = query.with_for_update(of=RefundModel)
        row = (
            await self.session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return refund_domain(row) if row else None

    async def refund_for_order(self, order_id, *, lock):
        return await self._refund(
            select(RefundModel).where(RefundModel.order_id == order_id), lock
        )

    async def owned(self, customer_id, order_id):
        return await self._refund(
            select(RefundModel)
            .join(OrderModel, OrderModel.id == RefundModel.order_id)
            .where(OrderModel.customer_id == customer_id, OrderModel.id == order_id)
        )

    async def scoped(self, branch_id, refund_id, *, lock):
        return await self._refund(
            select(RefundModel)
            .join(OrderModel, OrderModel.id == RefundModel.order_id)
            .where(OrderModel.branch_id == branch_id, RefundModel.id == refund_id),
            lock,
        )

    async def lock_refund(self, refund_id):
        return await self._refund(
            select(RefundModel).where(RefundModel.id == refund_id), True
        )

    async def list_branch(self, branch_id, status, method, limit, offset):
        query = (
            select(RefundModel)
            .join(OrderModel, OrderModel.id == RefundModel.order_id)
            .where(OrderModel.branch_id == branch_id)
        )
        if status is not None:
            query = query.where(RefundModel.status == status)
        if method is not None:
            query = query.where(RefundModel.method_type == method)
        query = (
            query.order_by(RefundModel.requested_at, RefundModel.id)
            .limit(limit)
            .offset(offset)
        )
        return [
            refund_domain(r)
            for r in (
                await self.session.execute(
                    query.execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        ]

    async def insert_refund(self, refund):
        await self._insert(RefundModel(**asdict(refund)))

    async def save_refund(self, original, updated):
        row = (
            await self._execute(
                update(RefundModel)
                .where(
                    RefundModel.id == original.id,
                    RefundModel.status == original.status,
                    RefundModel.reconciliation_required
                    == original.reconciliation_required,
                )
                .values(
                    status=updated.status,
                    refunded_at=updated.refunded_at,
                    reconciliation_required=updated.reconciliation_required,
                )
                .returning(RefundModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise RefundConflictError()
        return refund_domain(row)

    async def successful_capture(self, payment_id):
        rows = (
            (
                await self.session.execute(
                    select(PaymentAttemptModel)
                    .join(
                        PaymentModel, PaymentModel.id == PaymentAttemptModel.payment_id
                    )
                    .where(
                        PaymentAttemptModel.payment_id == payment_id,
                        PaymentAttemptModel.status == AttemptStatus.SUCCEEDED,
                        PaymentModel.status == PaymentStatus.PAID,
                    )
                    .order_by(PaymentAttemptModel.created_at, PaymentAttemptModel.id)
                    .limit(2)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != 1:
            raise RefundDataError()
        return attempt_domain(rows[0])

    async def view(self, refund):
        attempts = (
            (
                await self.session.execute(
                    select(RefundAttemptModel)
                    .where(RefundAttemptModel.refund_id == refund.id)
                    .order_by(
                        RefundAttemptModel.created_at.desc(),
                        RefundAttemptModel.id.desc(),
                    )
                    .limit(100)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        history = (
            (
                await self.session.execute(
                    select(RefundStatusHistoryModel)
                    .where(RefundStatusHistoryModel.refund_id == refund.id)
                    .order_by(
                        RefundStatusHistoryModel.created_at.desc(),
                        RefundStatusHistoryModel.id.desc(),
                    )
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return RefundView(
            refund=refund,
            attempts=tuple(refund_attempt_domain(a) for a in attempts),
            history=tuple(refund_history_domain(h) for h in history),
        )

    async def insert_attempt(self, attempt):
        await self._insert(RefundAttemptModel(**asdict(attempt)))

    async def save_attempt(self, original, updated):
        row = (
            await self._execute(
                update(RefundAttemptModel)
                .where(
                    RefundAttemptModel.id == original.id,
                    RefundAttemptModel.refund_id == original.refund_id,
                    RefundAttemptModel.status == original.status,
                )
                .values(
                    status=updated.status,
                    provider_reference=updated.provider_reference,
                    completed_at=updated.completed_at,
                    failure_code=updated.failure_code,
                )
                .returning(RefundAttemptModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise RefundConflictError()
        return refund_attempt_domain(row)

    async def _attempt(self, query, lock=False):
        if lock:
            query = query.with_for_update()
        row = (
            await self.session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return refund_attempt_domain(row) if row else None

    async def attempt_by_key(self, refund_id, key):
        return await self._attempt(
            select(RefundAttemptModel).where(
                RefundAttemptModel.refund_id == refund_id,
                RefundAttemptModel.idempotency_key == key,
            )
        )

    async def active_attempt(self, refund_id):
        return await self._attempt(
            select(RefundAttemptModel).where(
                RefundAttemptModel.refund_id == refund_id,
                RefundAttemptModel.status.in_(
                    (AttemptStatus.CREATED, AttemptStatus.PROCESSING)
                ),
            )
        )

    async def attempt_by_id(self, refund_id, attempt_id, *, lock):
        return await self._attempt(
            select(RefundAttemptModel).where(
                RefundAttemptModel.refund_id == refund_id,
                RefundAttemptModel.id == attempt_id,
            ),
            lock,
        )

    async def attempt_locator(self, provider, reference):
        row = (
            (
                await self.session.execute(
                    select(
                        RefundAttemptModel.refund_id,
                        RefundAttemptModel.id.label("attempt_id"),
                    ).where(
                        RefundAttemptModel.provider_code == provider,
                        RefundAttemptModel.provider_reference == reference,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return RefundAttemptLocator(**dict(row)) if row else None

    async def append_history(self, history):
        await self._insert(RefundStatusHistoryModel(**asdict(history)))

    async def get_or_insert_event(self, event):
        row = (
            await self._execute(
                insert(RefundProviderEventModel)
                .values(**asdict(event))
                .on_conflict_do_nothing(constraint="uq_refund_provider_events_key")
                .returning(RefundProviderEventModel)
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await self.session.execute(
                    select(RefundProviderEventModel)
                    .where(
                        RefundProviderEventModel.provider_code == event.provider_code,
                        RefundProviderEventModel.provider_event_id
                        == event.provider_event_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
        return refund_event_domain(row)

    async def save_event(self, original, updated):
        row = (
            await self._execute(
                update(RefundProviderEventModel)
                .where(
                    RefundProviderEventModel.id == original.id,
                    RefundProviderEventModel.processing_status
                    == original.processing_status,
                    RefundProviderEventModel.payload_hash == original.payload_hash,
                )
                .values(
                    processing_status=updated.processing_status,
                    processed_at=updated.processed_at,
                    refund_attempt_id=updated.refund_attempt_id,
                    reason_code=updated.reason_code,
                )
                .returning(RefundProviderEventModel.id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise RefundConflictError()

    async def commit(self):
        try:
            await self.session.commit()
        except IntegrityError:
            raise RefundConflictError() from None

    async def rollback(self):
        await self.session.rollback()
