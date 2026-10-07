from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.modules.cancellations.application.errors import CancellationConflictError
from app.modules.cancellations.domain.models import (
    CancellationRequest,
    CancellationSource,
    OrderCancellation,
    ReasonCode,
    RequestStatus,
)
from app.modules.cancellations.infrastructure.persistence.models import (
    CancellationRequestModel,
    OrderCancellationModel,
)
from app.shared.application.exceptions import DependencyUnavailableError


def request_domain(row):
    try:
        return CancellationRequest(
            **(row.model_dump() | {"status": RequestStatus(row.status)})
        )
    except (ValueError, TypeError):
        raise DependencyUnavailableError(
            "Cancellation request data is inconsistent"
        ) from None


def cancellation_domain(row):
    try:
        return OrderCancellation(
            **(
                row.model_dump()
                | {
                    "source": CancellationSource(row.source),
                    "reason_code": ReasonCode(row.reason_code),
                }
            )
        )
    except (ValueError, TypeError):
        raise DependencyUnavailableError(
            "Cancellation history is inconsistent"
        ) from None


class SQLAlchemyCancellationRepository:
    def __init__(self, session):
        self.session = session

    async def _execute(self, query):
        try:
            return await self.session.execute(query)
        except IntegrityError:
            raise CancellationConflictError(
                "CANCELLATION_REQUEST_ALREADY_PENDING"
            ) from None

    async def _insert(self, model):
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError:
            raise CancellationConflictError(
                "CANCELLATION_REQUEST_ALREADY_PENDING"
            ) from None

    async def pending_request(self, order_id):
        row = (
            await self.session.execute(
                select(CancellationRequestModel)
                .where(
                    CancellationRequestModel.order_id == order_id,
                    CancellationRequestModel.status == RequestStatus.PENDING,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return request_domain(row) if row else None

    async def request(self, branch_id, request_id, *, lock):
        query = select(CancellationRequestModel).where(
            CancellationRequestModel.branch_id == branch_id,
            CancellationRequestModel.id == request_id,
        )
        if lock:
            query = query.with_for_update()
        row = (
            await self.session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return request_domain(row) if row else None

    async def insert_request(self, request):
        await self._insert(CancellationRequestModel(**asdict(request)))

    async def save_request(self, original, updated):
        row = (
            await self._execute(
                update(CancellationRequestModel)
                .where(
                    CancellationRequestModel.id == original.id,
                    CancellationRequestModel.branch_id == original.branch_id,
                    CancellationRequestModel.order_id == original.order_id,
                    CancellationRequestModel.status == RequestStatus.PENDING,
                )
                .values(
                    status=updated.status,
                    evaluated_by_user_id=updated.evaluated_by_user_id,
                    evaluated_at=updated.evaluated_at,
                    evaluation_note=updated.evaluation_note,
                )
                .returning(CancellationRequestModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise CancellationConflictError("CANCELLATION_REQUEST_ALREADY_DECIDED")
        return request_domain(row)

    async def list_owned(self, customer_id, order_id, limit, offset):
        query = (
            select(CancellationRequestModel)
            .where(
                CancellationRequestModel.customer_id == customer_id,
                CancellationRequestModel.order_id == order_id,
            )
            .order_by(
                CancellationRequestModel.requested_at.desc(),
                CancellationRequestModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [
            request_domain(row)
            for row in (
                await self.session.execute(
                    query.execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        ]

    async def list_branch(self, branch_id, status, limit, offset):
        query = select(CancellationRequestModel).where(
            CancellationRequestModel.branch_id == branch_id
        )
        if status is not None:
            query = query.where(CancellationRequestModel.status == status)
        query = (
            query.order_by(
                CancellationRequestModel.requested_at, CancellationRequestModel.id
            )
            .limit(limit)
            .offset(offset)
        )
        return [
            request_domain(row)
            for row in (
                await self.session.execute(
                    query.execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        ]

    async def cancellation(self, order_id):
        row = (
            await self.session.execute(
                select(OrderCancellationModel).where(
                    OrderCancellationModel.order_id == order_id
                )
            )
        ).scalar_one_or_none()
        return cancellation_domain(row) if row else None

    async def insert_cancellation(self, cancellation):
        await self._insert(OrderCancellationModel(**asdict(cancellation)))

    async def commit(self):
        try:
            await self.session.commit()
        except IntegrityError:
            raise CancellationConflictError() from None

    async def rollback(self):
        await self.session.rollback()
