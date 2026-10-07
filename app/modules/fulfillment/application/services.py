from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from math import ceil
from uuid import UUID

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.fulfillment.application.dtos import (
    BulkReleaseResult,
    DelayDetectionResult,
    DeliveryQueueCard,
    PickupRecommendation,
    TransitionResult,
)
from app.modules.fulfillment.application.errors import (
    FulfillmentConflictError,
    FulfillmentDataError,
    FulfillmentNotFoundError,
    FulfillmentPermissionDeniedError,
)
from app.modules.fulfillment.application.ports import (
    FulfillmentAuthorization,
    FulfillmentOrdersGateway,
    FulfillmentRepository,
)
from app.modules.fulfillment.domain.models import (
    DELIVERY_OPERATIONAL_STATUSES,
    DeliveryAssignment,
    DeliveryDelayIncident,
    FulfillmentRuleError,
    clean_text,
)
from app.modules.fulfillment.domain.policies import (
    delay_seconds,
    evaluate_incident,
    identity_matches,
    is_delayed,
    recommended_release,
)
from app.modules.orders.domain.fulfillment import OrderFulfillmentContext
from app.modules.orders.domain.models import (
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    StatusHistory,
)
from app.shared.application.audit import AuditRecord, AuditRecorder
from app.shared.application.exceptions import RequestDataError
from app.shared.domain.time import utc_now


def bounds(limit: int, offset: int = 0) -> None:
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or not 0 <= offset <= 2147483647
    ):
        raise RequestDataError("Invalid fulfillment pagination")


class FulfillmentService:
    def __init__(
        self,
        repository: FulfillmentRepository,
        orders: FulfillmentOrdersGateway,
        authorization: FulfillmentAuthorization,
        audit: AuditRecorder,
        *,
        clock: Callable[[], datetime] = utc_now,
    ):
        self.repo = repository
        self.orders = orders
        self.authorization = authorization
        self.audit = audit
        self.clock = clock

    async def _authorize(
        self, principal: Principal, branch: UUID, permission: str
    ) -> UUID:
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
            or not await self.authorization.has_permission(
                principal.user_id, branch, permission
            )
        ):
            raise FulfillmentPermissionDeniedError()
        return principal.user_id

    @staticmethod
    def _gate(order: OrderFulfillmentContext, mode: OrderMode) -> None:
        if (
            order.mode != mode
            or order.payment_method_type != PaymentMethodType.ONLINE
            or order.payment_status != PaymentStatus.PAID
            or order.confirmed_at is None
        ):
            raise FulfillmentConflictError()

    async def _order(
        self, branch: UUID, order_id: UUID, mode: OrderMode
    ) -> OrderFulfillmentContext:
        order = await self.orders.lock_order(branch, order_id)
        if order is None:
            raise FulfillmentNotFoundError()
        self._gate(order, mode)
        return order

    async def _transaction(self, work):
        try:
            result = await work()
            await self.repo.commit()
            return result
        except OrderRuleError:
            await self.repo.rollback()
            raise FulfillmentConflictError() from None
        except FulfillmentRuleError:
            await self.repo.rollback()
            raise FulfillmentDataError() from None
        except Exception:
            await self.repo.rollback()
            raise

    async def _transition(
        self,
        order: OrderFulfillmentContext,
        target: OrderStatus,
        actor: UUID,
        now: datetime,
        reason: str,
    ) -> TransitionResult:
        changed = order.status != target
        if changed:
            await self.orders.transition(
                order,
                StatusHistory(
                    from_status=order.status,
                    to_status=target,
                    changed_by_user_id=actor,
                    created_at=now,
                    reason=reason,
                ),
            )
        return TransitionResult(
            order_id=order.id,
            order_number=order.order_number,
            status=target,
            changed=changed,
        )

    @staticmethod
    def _recommendation(order, settings, depth, now) -> PickupRecommendation:
        release, ready = recommended_release(order.requested_pickup_at, settings, depth)
        return PickupRecommendation(
            order_id=order.id,
            order_number=order.order_number,
            requested_pickup_at=order.requested_pickup_at,
            initial_release_at=order.calculated_kitchen_release_at,
            recommended_release_at=release,
            initial_estimated_ready_at=order.estimated_ready_at,
            estimated_ready_at=ready,
            queue_depth=depth,
            minutes_until_release=max(0, ceil((release - now).total_seconds() / 60)),
            is_due=now >= release,
        )

    async def pickup_due(self, principal, branch, limit=50, offset=0):
        bounds(limit, offset)
        await self._authorize(principal, branch, "FULFILLMENT_VIEW")
        settings, depth = await self.orders.settings_and_queue(branch)
        now = self.clock()
        return [
            self._recommendation(o, settings, depth, now)
            for o in await self.orders.pickup_candidates(branch, limit, offset)
        ]

    async def release_pickup(self, principal, branch, order_id):
        async def work():
            actor = await self._authorize(principal, branch, "FULFILLMENT_MANAGE")
            order = await self._order(branch, order_id, OrderMode.PICKUP)
            if order.status == OrderStatus.WAITING:
                return await self._transition(
                    order,
                    OrderStatus.WAITING,
                    actor,
                    self.clock(),
                    "Scheduled pickup released to kitchen",
                )
            if order.status != OrderStatus.SCHEDULED:
                raise FulfillmentConflictError()
            settings, depth = await self.orders.settings_and_queue(branch)
            now = self.clock()
            if not self._recommendation(order, settings, depth, now).is_due:
                raise FulfillmentConflictError("PICKUP_NOT_DUE")
            return await self._transition(
                order,
                OrderStatus.WAITING,
                actor,
                now,
                "Scheduled pickup released to kitchen",
            )

        return await self._transaction(work)

    async def release_due_pickups(self, principal, branch, limit=50):
        bounds(limit)

        async def work():
            actor = await self._authorize(principal, branch, "FULFILLMENT_MANAGE")
            settings, depth = await self.orders.settings_and_queue(branch)
            now = self.clock()
            # One queue snapshot per bounded batch, with SKIP LOCKED in PostgreSQL.
            prep = (
                settings.default_prep_minutes
                + depth * settings.queue_delay_per_order_minutes
                + settings.pickup_buffer_minutes
            )
            candidates = await self.orders.pickup_candidates(
                branch, limit, now=now, prep_minutes=prep, lock=True
            )
            results = []
            for order in candidates:
                self._gate(order, OrderMode.PICKUP)
                if (
                    order.status != OrderStatus.SCHEDULED
                    or not self._recommendation(order, settings, depth, now).is_due
                ):
                    raise FulfillmentDataError()
                results.append(
                    await self._transition(
                        order,
                        OrderStatus.WAITING,
                        actor,
                        now,
                        "Scheduled pickup released to kitchen",
                    )
                )
            return BulkReleaseResult(
                evaluated=len(candidates),
                released=len(results),
                orders=tuple(results),
                queue_depth=depth,
            )

        return await self._transaction(work)

    async def complete_pickup(self, principal, branch, order_id, name, phone):
        async def work():
            actor = await self._authorize(principal, branch, "FULFILLMENT_MANAGE")
            order = await self._order(branch, order_id, OrderMode.PICKUP)
            if order.status not in {
                OrderStatus.READY_FOR_PICKUP,
                OrderStatus.PICKED_UP,
            }:
                raise FulfillmentConflictError()
            # Retries still validate identity; no duplicate or raw input is persisted.
            try:
                matches = identity_matches(
                    name, phone, order.pickup_name_snapshot, order.pickup_phone_snapshot
                )
            except FulfillmentRuleError:
                matches = False
            if not matches:
                raise FulfillmentConflictError("PICKUP_IDENTITY_MISMATCH")
            return await self._transition(
                order,
                OrderStatus.PICKED_UP,
                actor,
                self.clock(),
                "Pickup identity verified and handed over",
            )

        return await self._transaction(work)

    async def delivery_queue(self, principal, branch, status=None, limit=50, offset=0):
        bounds(limit, offset)
        if status is not None and status not in DELIVERY_OPERATIONAL_STATUSES:
            raise RequestDataError("Invalid delivery queue filter")
        await self._authorize(principal, branch, "FULFILLMENT_VIEW")
        rows = await self.orders.delivery_queue(branch, status, limit, offset)
        assignments = await self.repo.active_assignments([o.id for o in rows])
        now = self.clock()
        return [
            DeliveryQueueCard(
                order=o,
                active_assignment=assignments.get(o.id),
                current_delay_seconds=delay_seconds(o, now),
                is_delayed=is_delayed(o, now),
            )
            for o in rows
        ]

    async def _audit(self, actor, branch, action, entity, entity_id, before, after):
        await self.audit.record(
            AuditRecord(
                actor_user_id=actor,
                branch_id=branch,
                action=action,
                entity_type=entity,
                entity_id=entity_id,
                before_state=before,
                after_state=after,
            )
        )

    async def assign_delivery(self, principal, branch, order_id, assigned_user_id):
        async def work():
            actor = await self._authorize(principal, branch, "DELIVERY_ASSIGN")
            order = await self._order(branch, order_id, OrderMode.DELIVERY)
            if order.status not in {
                OrderStatus.WAITING,
                OrderStatus.PREPARING,
                OrderStatus.READY,
            }:
                raise FulfillmentConflictError("DELIVERY_ASSIGNMENT_INVALID")
            old = await self.repo.active_assignment(order.id, lock=True)
            now = self.clock()
            if not await self.authorization.staff_is_active(
                assigned_user_id, branch, now
            ):
                raise FulfillmentConflictError("DELIVERY_ASSIGNEE_INVALID")
            if old is not None and old.assigned_user_id == assigned_user_id:
                return old
            if old is not None:
                await self.repo.close_assignment(
                    old,
                    replace(
                        old,
                        unassigned_at=now,
                        unassigned_by_user_id=actor,
                        reason="Reassigned by authorized staff",
                    ),
                )
            new = DeliveryAssignment(
                order_id=order.id,
                assigned_user_id=assigned_user_id,
                assigned_by_user_id=actor,
                assigned_at=now,
                created_at=now,
            )
            await self.repo.insert_assignment(new)
            await self._audit(
                actor,
                branch,
                "DELIVERY_REASSIGNED" if old else "DELIVERY_ASSIGNED",
                "delivery_assignment",
                new.id,
                {"assigned_user_id": str(old.assigned_user_id)} if old else None,
                {"order_id": str(order.id), "assigned_user_id": str(assigned_user_id)},
            )
            return new

        return await self._transaction(work)

    async def unassign_delivery(self, principal, branch, order_id):
        async def work():
            actor = await self._authorize(principal, branch, "DELIVERY_ASSIGN")
            order = await self._order(branch, order_id, OrderMode.DELIVERY)
            if order.status not in {
                OrderStatus.WAITING,
                OrderStatus.PREPARING,
                OrderStatus.READY,
            }:
                raise FulfillmentConflictError("DELIVERY_ASSIGNMENT_INVALID")
            old = await self.repo.active_assignment(order.id, lock=True)
            if old is not None:
                await self.repo.close_assignment(
                    old,
                    replace(
                        old,
                        unassigned_at=self.clock(),
                        unassigned_by_user_id=actor,
                        reason="Unassigned by authorized staff",
                    ),
                )
                await self._audit(
                    actor,
                    branch,
                    "DELIVERY_UNASSIGNED",
                    "delivery_assignment",
                    old.id,
                    {"assigned_user_id": str(old.assigned_user_id)},
                    {"active": False},
                )

        await self._transaction(work)

    async def dispatch_delivery(self, principal, branch, order_id):
        async def work():
            actor = await self._authorize(principal, branch, "FULFILLMENT_MANAGE")
            order = await self._order(branch, order_id, OrderMode.DELIVERY)
            if order.status not in {OrderStatus.READY, OrderStatus.OUT_FOR_DELIVERY}:
                raise FulfillmentConflictError()
            assignment = await self.repo.active_assignment(order.id, lock=True)
            if assignment is None:
                raise FulfillmentConflictError("DELIVERY_ASSIGNMENT_REQUIRED")
            if not await self.authorization.staff_is_active(
                assignment.assigned_user_id, branch, self.clock()
            ):
                raise FulfillmentConflictError("DELIVERY_ASSIGNEE_INVALID")
            return await self._transition(
                order,
                OrderStatus.OUT_FOR_DELIVERY,
                actor,
                self.clock(),
                "Delivery dispatched with active assignment",
            )

        return await self._transaction(work)

    async def complete_delivery(self, principal, branch, order_id):
        async def work():
            actor = await self._authorize(principal, branch, "FULFILLMENT_MANAGE")
            order = await self._order(branch, order_id, OrderMode.DELIVERY)
            if order.status == OrderStatus.DELIVERED:
                return TransitionResult(
                    order_id=order.id,
                    order_number=order.order_number,
                    status=order.status,
                    changed=False,
                )
            if order.status != OrderStatus.OUT_FOR_DELIVERY:
                raise FulfillmentConflictError()
            assignment = await self.repo.active_assignment(order.id, lock=True)
            if assignment is None:
                raise FulfillmentConflictError("DELIVERY_ASSIGNMENT_REQUIRED")
            now = self.clock()
            result = await self._transition(
                order,
                OrderStatus.DELIVERED,
                actor,
                now,
                "Delivery completed by authorized staff",
            )
            await self.repo.close_assignment(
                assignment, replace(assignment, completed_at=now)
            )
            return result

        return await self._transaction(work)

    async def detect_delivery_delays(
        self, principal, branch, limit=50, after_order_number=0
    ):
        bounds(limit)
        if (
            type(after_order_number) is not int
            or not 0 <= after_order_number <= 9223372036854775807
        ):
            raise RequestDataError("Invalid delivery scan cursor")

        async def work():
            await self._authorize(principal, branch, "DELIVERY_DELAY_REVIEW")
            now = self.clock()
            rows = await self.orders.delay_candidates(
                branch, now, limit, after_order_number
            )
            created = 0
            for order in rows:
                self._gate(order, OrderMode.DELIVERY)
                if not is_delayed(order, now):
                    raise FulfillmentDataError()
                incident = DeliveryDelayIncident(
                    order_id=order.id,
                    branch_id=branch,
                    committed_eta=order.estimated_delivery_at,
                    observed_order_status=order.status,
                    delay_seconds_at_detection=delay_seconds(order, now),
                    detected_at=now,
                    created_at=now,
                    updated_at=now,
                )
                created += int(await self.repo.insert_incident(incident))
            return DelayDetectionResult(
                evaluated=len(rows),
                new_incidents=created,
                existing_incidents=len(rows) - created,
                next_order_number=rows[-1].order_number if len(rows) == limit else None,
            )

        return await self._transaction(work)

    async def list_delays(self, principal, branch, status=None, limit=50, offset=0):
        bounds(limit, offset)
        await self._authorize(principal, branch, "FULFILLMENT_VIEW")
        return await self.repo.list_incidents(branch, status, limit, offset)

    async def decide_delay(
        self,
        principal,
        branch,
        incident_id,
        target,
        responsibility=None,
        note=None,
        remediation=None,
    ):
        async def work():
            actor = await self._authorize(principal, branch, "DELIVERY_DELAY_REVIEW")
            incident = await self.repo.lock_incident(branch, incident_id)
            if incident is None:
                raise FulfillmentNotFoundError(incident=True)
            if note is not None:
                clean_text(note)
            if remediation is not None:
                clean_text(remediation)
            try:
                updated = evaluate_incident(
                    incident,
                    target,
                    actor,
                    self.clock(),
                    responsibility,
                    note,
                    remediation,
                )
            except FulfillmentRuleError:
                raise FulfillmentConflictError(
                    "DELIVERY_DELAY_ALREADY_DECIDED"
                ) from None
            if updated == incident:
                return incident
            updated = await self.repo.save_decision(incident, updated)
            await self._audit(
                actor,
                branch,
                "DELIVERY_DELAY_" + target.value,
                "delivery_delay_incident",
                incident.id,
                {"decision_status": incident.decision_status.value},
                {"decision_status": target.value},
            )
            return updated

        return await self._transaction(work)
