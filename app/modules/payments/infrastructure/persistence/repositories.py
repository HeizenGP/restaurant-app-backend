"""Repositories do not commit; the use case owns each atomic unit of work."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Executable

from app.modules.orders.domain.models import PaymentMethodType
from app.modules.orders.infrastructure.persistence.models import OrderModel
from app.modules.payments.application.dtos import AttemptLocator, PaymentView
from app.modules.payments.application.errors import (
    PaymentConflictError,
    PaymentDataError,
)
from app.modules.payments.domain.models import (
    ACTIVE_ATTEMPT_STATUSES,
    AttemptStatus,
    ClientAction,
    EventStatus,
    Payment,
    PaymentAttempt,
    PaymentStatus,
    PaymentStatusHistory,
    ProviderEvent,
    VerifiedResult,
)
from app.modules.payments.infrastructure.persistence.models import (
    PaymentAttemptModel,
    PaymentModel,
    PaymentProviderEventModel,
    PaymentStatusHistoryModel,
)


def payment_domain(row: PaymentModel) -> Payment:
    try:
        return Payment(
            **(
                row.model_dump()
                | {
                    "method_type": PaymentMethodType(row.method_type),
                    "status": PaymentStatus(row.status),
                }
            )
        )
    except (ValueError, TypeError):
        raise PaymentDataError() from None


def attempt_domain(row: PaymentAttemptModel) -> PaymentAttempt:
    try:
        data = row.model_dump()
        kind, value = data.pop("client_action_kind"), data.pop("client_action_value")
        if (kind is None) != (value is None):
            raise ValueError("Incomplete client action")
        return PaymentAttempt(
            **(
                data
                | {
                    "status": AttemptStatus(row.status),
                    "client_action": ClientAction(kind=kind, value=value)
                    if kind
                    else None,
                }
            )
        )
    except (ValueError, TypeError):
        raise PaymentDataError() from None


def event_domain(row: PaymentProviderEventModel) -> ProviderEvent:
    try:
        return ProviderEvent(
            **(
                row.model_dump()
                | {
                    "result": VerifiedResult(row.result),
                    "processing_status": EventStatus(row.processing_status),
                }
            )
        )
    except (ValueError, TypeError):
        raise PaymentDataError() from None


def attempt_values(attempt: PaymentAttempt) -> dict:
    data = asdict(attempt)
    data.pop("client_action")
    data["client_action_kind"] = (
        attempt.client_action.kind if attempt.client_action else None
    )
    data["client_action_value"] = (
        attempt.client_action.value if attempt.client_action else None
    )
    return data


class SQLAlchemyPaymentRepository:
    async def ensure_cancelled_refund(self, order, payment, now) -> None:
        from app.modules.payments.application.refund_registration import (
            RefundRegistrationService,
        )
        from app.modules.payments.infrastructure.persistence import refund_repositories

        await RefundRegistrationService(
            refund_repositories.SQLAlchemyRefundRepository(self._session)
        ).register_full(payment, order.id, order.total, order.payment_method_type, now)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError:
            raise PaymentConflictError("PAYMENT_IDEMPOTENCY_CONFLICT") from None

    async def _execute(self, statement: Executable) -> Result[Any]:
        try:
            return await self._session.execute(statement)
        except IntegrityError:
            raise PaymentConflictError("PAYMENT_IDEMPOTENCY_CONFLICT") from None

    async def get_owned(self, customer_id: UUID, order_id: UUID) -> PaymentView | None:
        row = (
            await self._session.execute(
                select(PaymentModel)
                .join(OrderModel, OrderModel.id == PaymentModel.order_id)
                .where(OrderModel.customer_id == customer_id, OrderModel.id == order_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return await self.view(payment_domain(row)) if row else None

    async def payment_for_order(self, order_id: UUID, *, lock: bool) -> Payment | None:
        query = select(PaymentModel).where(PaymentModel.order_id == order_id)
        if lock:
            query = query.with_for_update()
        row = (
            await self._session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return payment_domain(row) if row else None

    async def insert_payment(self, payment: Payment) -> None:
        self._session.add(PaymentModel(**asdict(payment)))
        await self._flush()

    async def save_payment(self, original: Payment, updated: Payment) -> Payment:
        row = (
            await self._execute(
                update(PaymentModel)
                .where(
                    PaymentModel.id == original.id,
                    PaymentModel.status == original.status,
                    PaymentModel.reconciliation_required
                    == original.reconciliation_required,
                )
                .values(
                    status=updated.status,
                    paid_at=updated.paid_at,
                    reconciliation_required=updated.reconciliation_required,
                )
                .returning(PaymentModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise PaymentConflictError()
        return payment_domain(row)

    async def view(self, payment: Payment) -> PaymentView:
        rows = (
            (
                await self._session.execute(
                    select(PaymentAttemptModel)
                    .where(PaymentAttemptModel.payment_id == payment.id)
                    .order_by(
                        PaymentAttemptModel.created_at.desc(),
                        PaymentAttemptModel.id.desc(),
                    )
                    .limit(100)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return PaymentView(
            payment=payment, attempts=tuple(attempt_domain(r) for r in rows)
        )

    async def insert_attempt(self, attempt: PaymentAttempt) -> None:
        self._session.add(PaymentAttemptModel(**attempt_values(attempt)))
        await self._flush()

    async def save_attempt(
        self, original: PaymentAttempt, updated: PaymentAttempt
    ) -> PaymentAttempt:
        data = attempt_values(updated)
        mutable = {
            k: data[k]
            for k in (
                "status",
                "provider_reference",
                "failure_code",
                "client_action_kind",
                "client_action_value",
                "completed_at",
            )
        }
        row = (
            await self._execute(
                update(PaymentAttemptModel)
                .where(
                    PaymentAttemptModel.id == original.id,
                    PaymentAttemptModel.payment_id == original.payment_id,
                    PaymentAttemptModel.status == original.status,
                )
                .values(**mutable)
                .returning(PaymentAttemptModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise PaymentConflictError()
        return attempt_domain(row)

    async def attempt_by_key(self, payment_id: UUID, key: str) -> PaymentAttempt | None:
        row = (
            await self._session.execute(
                select(PaymentAttemptModel)
                .where(
                    PaymentAttemptModel.payment_id == payment_id,
                    PaymentAttemptModel.idempotency_key == key,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return attempt_domain(row) if row else None

    async def active_attempt(self, payment_id: UUID) -> PaymentAttempt | None:
        row = (
            await self._session.execute(
                select(PaymentAttemptModel)
                .where(
                    PaymentAttemptModel.payment_id == payment_id,
                    PaymentAttemptModel.status.in_(ACTIVE_ATTEMPT_STATUSES),
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return attempt_domain(row) if row else None

    async def attempt_by_id(
        self, payment_id: UUID, attempt_id: UUID, *, lock: bool
    ) -> PaymentAttempt | None:
        query = select(PaymentAttemptModel).where(
            PaymentAttemptModel.payment_id == payment_id,
            PaymentAttemptModel.id == attempt_id,
        )
        if lock:
            query = query.with_for_update()
        row = (
            await self._session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return attempt_domain(row) if row else None

    async def attempt_locator(
        self, provider: str, reference: str
    ) -> AttemptLocator | None:
        row = (
            (
                await self._session.execute(
                    select(
                        PaymentAttemptModel.id.label("attempt_id"),
                        PaymentModel.id.label("payment_id"),
                        PaymentModel.order_id,
                    )
                    .join(
                        PaymentModel, PaymentModel.id == PaymentAttemptModel.payment_id
                    )
                    .where(
                        PaymentAttemptModel.provider_code == provider,
                        PaymentAttemptModel.provider_reference == reference,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return AttemptLocator(**dict(row)) if row else None

    async def append_history(self, history: PaymentStatusHistory) -> None:
        self._session.add(PaymentStatusHistoryModel(**asdict(history)))
        await self._flush()

    async def get_or_insert_event(self, event: ProviderEvent) -> ProviderEvent:
        row = (
            await self._execute(
                insert(PaymentProviderEventModel)
                .values(**asdict(event))
                .on_conflict_do_nothing(constraint="uq_payment_provider_events_key")
                .returning(PaymentProviderEventModel)
            )
        ).scalar_one_or_none()
        if row is None:
            row = (
                await self._session.execute(
                    select(PaymentProviderEventModel)
                    .where(
                        PaymentProviderEventModel.provider_code == event.provider_code,
                        PaymentProviderEventModel.provider_event_id
                        == event.provider_event_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one()
        return event_domain(row)

    async def save_event(self, original: ProviderEvent, updated: ProviderEvent) -> None:
        row_id = (
            await self._execute(
                update(PaymentProviderEventModel)
                .where(
                    PaymentProviderEventModel.id == original.id,
                    PaymentProviderEventModel.processing_status
                    == original.processing_status,
                    PaymentProviderEventModel.payload_hash == original.payload_hash,
                )
                .values(
                    processing_status=updated.processing_status,
                    payment_attempt_id=updated.payment_attempt_id,
                    reason_code=updated.reason_code,
                    processed_at=updated.processed_at,
                )
                .returning(PaymentProviderEventModel.id)
            )
        ).scalar_one_or_none()
        if row_id is None:
            raise PaymentConflictError()

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError:
            raise PaymentConflictError("PAYMENT_IDEMPOTENCY_CONFLICT") from None

    async def rollback(self) -> None:
        await self._session.rollback()
