from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fulfillment.application.errors import (
    FulfillmentConflictError,
    FulfillmentDataError,
)
from app.modules.fulfillment.domain.models import (
    DecisionStatus,
    DeliveryAssignment,
    DeliveryDelayIncident,
)
from app.modules.fulfillment.infrastructure.persistence.models import (
    DeliveryAssignmentModel,
    DeliveryDelayIncidentModel,
)
from app.modules.orders.domain.models import OrderStatus


def assignment_domain(row):
    try:
        return DeliveryAssignment(**row.model_dump())
    except (ValueError, TypeError):
        raise FulfillmentDataError() from None


def incident_domain(row):
    try:
        return DeliveryDelayIncident(
            **(
                row.model_dump()
                | {
                    "observed_order_status": OrderStatus(row.observed_order_status),
                    "decision_status": DecisionStatus(row.decision_status),
                }
            )
        )
    except (ValueError, TypeError):
        raise FulfillmentDataError() from None


def active_conditions():
    return (
        DeliveryAssignmentModel.unassigned_at.is_(None),
        DeliveryAssignmentModel.completed_at.is_(None),
    )


class SQLAlchemyFulfillmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _execute(self, statement):
        try:
            return await self.session.execute(statement)
        except IntegrityError:
            raise FulfillmentConflictError() from None

    async def _flush(self):
        try:
            await self.session.flush()
        except IntegrityError:
            raise FulfillmentConflictError() from None

    async def active_assignments(self, order_ids):
        if not order_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(DeliveryAssignmentModel)
                    .where(
                        DeliveryAssignmentModel.order_id.in_(order_ids),
                        *active_conditions(),
                    )
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return {r.order_id: assignment_domain(r) for r in rows}

    async def active_assignment(self, order_id, *, lock):
        query = select(DeliveryAssignmentModel).where(
            DeliveryAssignmentModel.order_id == order_id, *active_conditions()
        )
        if lock:
            query = query.with_for_update()
        row = (
            await self.session.execute(query.execution_options(populate_existing=True))
        ).scalar_one_or_none()
        return assignment_domain(row) if row else None

    async def insert_assignment(self, assignment):
        self.session.add(DeliveryAssignmentModel(**asdict(assignment)))
        await self._flush()

    async def close_assignment(self, original, updated):
        row = (
            await self._execute(
                update(DeliveryAssignmentModel)
                .where(
                    DeliveryAssignmentModel.id == original.id,
                    DeliveryAssignmentModel.order_id == original.order_id,
                    *active_conditions(),
                )
                .values(
                    unassigned_at=updated.unassigned_at,
                    unassigned_by_user_id=updated.unassigned_by_user_id,
                    completed_at=updated.completed_at,
                    reason=updated.reason,
                )
                .returning(DeliveryAssignmentModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise FulfillmentConflictError("DELIVERY_ASSIGNMENT_INVALID")
        return assignment_domain(row)

    async def insert_incident(self, incident):
        value = (
            await self._execute(
                insert(DeliveryDelayIncidentModel)
                .values(**asdict(incident))
                .on_conflict_do_nothing(constraint="uq_delivery_delay_incidents_order")
                .returning(DeliveryDelayIncidentModel.id)
            )
        ).scalar_one_or_none()
        return value is not None

    async def list_incidents(self, branch_id, status, limit, offset):
        query = select(DeliveryDelayIncidentModel).where(
            DeliveryDelayIncidentModel.branch_id == branch_id
        )
        if status is not None:
            query = query.where(DeliveryDelayIncidentModel.decision_status == status)
        query = (
            query.order_by(
                DeliveryDelayIncidentModel.detected_at.desc(),
                DeliveryDelayIncidentModel.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return [
            incident_domain(r)
            for r in (
                await self.session.execute(
                    query.execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        ]

    async def lock_incident(self, branch_id, incident_id):
        row = (
            await self.session.execute(
                select(DeliveryDelayIncidentModel)
                .where(
                    DeliveryDelayIncidentModel.branch_id == branch_id,
                    DeliveryDelayIncidentModel.id == incident_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return incident_domain(row) if row else None

    async def save_decision(self, original, updated):
        mutable = {
            k: asdict(updated)[k]
            for k in (
                "decision_status",
                "evaluated_by_user_id",
                "evaluated_at",
                "customer_responsibility",
                "evaluation_note",
                "remediation_description",
            )
        }
        row = (
            await self._execute(
                update(DeliveryDelayIncidentModel)
                .where(
                    DeliveryDelayIncidentModel.id == original.id,
                    DeliveryDelayIncidentModel.branch_id == original.branch_id,
                    DeliveryDelayIncidentModel.decision_status == DecisionStatus.OPEN,
                )
                .values(**mutable)
                .returning(DeliveryDelayIncidentModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise FulfillmentConflictError("DELIVERY_DELAY_ALREADY_DECIDED")
        return incident_domain(row)

    async def commit(self):
        try:
            await self.session.commit()
        except IntegrityError:
            raise FulfillmentConflictError() from None

    async def rollback(self):
        await self.session.rollback()
