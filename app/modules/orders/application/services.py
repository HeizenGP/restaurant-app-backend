import hashlib
import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.cart.application.errors import CartNotFoundError
from app.modules.cart.application.services import customer_identity
from app.modules.orders.application.dtos import OrderCreate
from app.modules.orders.application.errors import (
    InvalidOrderDataError,
    OrderConflictError,
    OrderNotFoundError,
    OrderPermissionDeniedError,
    OrderResourceNotFoundError,
    OrderUniqueConflictError,
)
from app.modules.orders.application.ports import (
    CartCheckoutGateway,
    CustomerCheckoutGateway,
    KitchenLoadEstimator,
    OrderAuthorization,
    OrderRepository,
    OrderSettingsRepository,
)
from app.modules.orders.domain.models import (
    BranchOrderSettings,
    DeliveryDetails,
    DeliveryZone,
    LocalDetails,
    Order,
    OrderMode,
    OrderRuleError,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
    PickupDetails,
    RestaurantTable,
    ScheduleCalculation,
    StatusHistory,
    aware,
    money,
)
from app.modules.orders.domain.policies import (
    initial_status,
    pickup_times,
    within_branch_hours,
)
from app.modules.orders.domain.transitions import validate_transition
from app.shared.domain.time import utc_now


def validate_command(command: OrderCreate) -> None:
    if not isinstance(command.mode, OrderMode) or not isinstance(
        command.payment_method, PaymentMethodType
    ):
        raise InvalidOrderDataError()
    shape = (
        command.table_qr_token is not None,
        command.requested_pickup_at is not None,
        command.address_id is not None,
    )
    if shape != {
        OrderMode.LOCAL: (True, False, False),
        OrderMode.PICKUP: (False, True, False),
        OrderMode.DELIVERY: (False, False, True),
    }[command.mode] or (
        command.mode != OrderMode.LOCAL
        and command.payment_method != PaymentMethodType.ONLINE
    ):
        raise InvalidOrderDataError()
    if command.requested_pickup_at is not None:
        try:
            aware(command.requested_pickup_at)
        except OrderRuleError:
            raise InvalidOrderDataError() from None


def request_fingerprint(customer_id: UUID, cart_id: UUID, command: OrderCreate) -> str:
    fields = asdict(command)
    fields["customer_id"] = str(customer_id)
    fields["source_cart_id"] = str(cart_id)
    for key, value in fields.items():
        if isinstance(value, datetime):
            fields[key] = value.astimezone(UTC).isoformat()
        elif isinstance(value, UUID):
            fields[key] = str(value)
    return hashlib.sha256(
        json.dumps(
            fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


class OrderService:
    def __init__(
        self,
        repository: OrderRepository,
        checkout: CartCheckoutGateway,
        customers: CustomerCheckoutGateway,
        settings: OrderSettingsRepository,
        estimator: KitchenLoadEstimator,
        authorization: OrderAuthorization,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._checkout = checkout
        self._customers = customers
        self._settings = settings
        self._estimator = estimator
        self._authorization = authorization
        self._clock = clock

    @staticmethod
    def _replay(order: Order, customer_id: UUID, command: OrderCreate) -> Order:
        if order.request_fingerprint != request_fingerprint(
            customer_id, order.source_cart_id, command
        ):
            raise OrderConflictError("IDEMPOTENCY_KEY_REUSED")
        return order

    async def create(
        self, principal: Principal, key: str, command: OrderCreate
    ) -> Order:
        customer_id = customer_identity(principal)
        validate_command(command)
        if (
            not isinstance(key, str)
            or re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", key) is None
        ):
            raise InvalidOrderDataError()
        try:
            previous = await self._repository.by_idempotency(customer_id, key)
            if previous is not None:
                return self._replay(previous, customer_id, command)
            # Serialize same-customer checkouts, including requests which started
            # before a competing transaction committed its idempotency record.
            customer = await self._customers.lock_customer(customer_id)
            if customer is None:
                raise OrderResourceNotFoundError("CUSTOMER_NOT_FOUND")
            previous = await self._repository.by_idempotency(customer_id, key)
            if previous is not None:
                return self._replay(previous, customer_id, command)
            cart = await self._checkout.get_and_lock_active_cart(customer_id)
            if cart is None:
                if await self._checkout.has_checked_out_cart(customer_id):
                    raise OrderConflictError("ORDER_ALREADY_CREATED")
                raise CartNotFoundError()
            items = await self._checkout.validate_for_checkout(cart)
            if not items:
                raise OrderConflictError("EMPTY_CART")
            subtotal = money(
                sum((item.line_total_snapshot for item in items), start=money_zero())
            )
            settings = await self._settings.get_settings(cart.branch_id, lock=True)
            now = self._clock().astimezone(UTC)
            local = pickup = delivery = schedule = None
            fee = money_zero()
            if command.mode == OrderMode.LOCAL:
                table = await self._settings.table_by_qr(command.table_qr_token)
                if table is None or not table.is_active:
                    raise OrderResourceNotFoundError("TABLE_NOT_FOUND")
                if table.branch_id != cart.branch_id:
                    raise OrderConflictError("TABLE_BRANCH_MISMATCH")
                local = LocalDetails(
                    restaurant_table_id=table.id,
                    table_label_snapshot=table.label,
                    payment_choice=command.payment_method,
                    cash_confirmation_required_snapshot=settings.cash_payment_requires_confirmation,
                )
            elif command.mode == OrderMode.PICKUP:
                requested = command.requested_pickup_at.astimezone(UTC)
                hours = await self._settings.branch_hours(cart.branch_id)
                if not within_branch_hours(requested, settings.timezone, hours.hours):
                    raise OrderConflictError("PICKUP_TIME_UNAVAILABLE")
                estimate = await self._estimator.estimate(cart.branch_id, settings)
                try:
                    release, ready = pickup_times(
                        now,
                        requested,
                        estimate.total_minutes,
                        settings.pickup_buffer_minutes,
                    )
                except OrderRuleError:
                    raise OrderConflictError("PICKUP_TIME_UNAVAILABLE") from None
                pickup = PickupDetails(
                    requested_pickup_at=requested,
                    calculated_kitchen_release_at=release,
                    estimated_ready_at=ready,
                    pickup_name_snapshot=customer.full_name,
                    pickup_phone_snapshot=customer.phone,
                )
                schedule = ScheduleCalculation(
                    queue_depth=estimate.queue_depth,
                    base_prep_minutes=estimate.base_prep_minutes,
                    queue_delay_minutes=estimate.queue_delay_minutes,
                    buffer_minutes=settings.pickup_buffer_minutes,
                    travel_minutes=0,
                    calculated_release_at=release,
                    estimated_ready_at=ready,
                    created_at=now,
                )
            else:
                address = await self._customers.address(customer_id, command.address_id)
                if address is None:
                    raise OrderResourceNotFoundError("DELIVERY_ADDRESS_NOT_FOUND")
                zone = await self._settings.resolve_zone(
                    cart.branch_id, address.district
                )
                if zone is None:
                    raise OrderConflictError("DELIVERY_ZONE_UNAVAILABLE")
                if subtotal < settings.delivery_minimum_order:
                    raise OrderConflictError("DELIVERY_MINIMUM_NOT_MET")
                estimate = await self._estimator.estimate(cart.branch_id, settings)
                fee = money_zero() if zone.is_free else zone.delivery_fee
                travel = zone.estimated_travel_minutes
                if travel is None:
                    travel = settings.delivery_default_travel_minutes
                ready = now + timedelta(minutes=estimate.total_minutes)
                delivery = DeliveryDetails(
                    customer_address_id=address.id,
                    delivery_zone_id=zone.id,
                    delivery_zone_name_snapshot=zone.name,
                    **{
                        name + "_snapshot": getattr(address, name)
                        for name in (
                            "recipient_name",
                            "recipient_phone",
                            "address_line",
                            "reference_text",
                            "district",
                            "city",
                            "department",
                            "latitude",
                            "longitude",
                        )
                    },
                    delivery_fee_snapshot=fee,
                    estimated_delivery_at=ready + timedelta(minutes=travel),
                )
                schedule = ScheduleCalculation(
                    queue_depth=estimate.queue_depth,
                    base_prep_minutes=estimate.base_prep_minutes,
                    queue_delay_minutes=estimate.queue_delay_minutes,
                    buffer_minutes=0,
                    travel_minutes=travel,
                    calculated_release_at=None,
                    estimated_ready_at=ready,
                    created_at=now,
                )
            status = initial_status(command.mode, command.payment_method, settings)
            order = Order(
                source_cart_id=cart.id,
                customer_id=customer_id,
                branch_id=cart.branch_id,
                mode=command.mode,
                status=status,
                payment_method_type=command.payment_method,
                payment_status=PaymentStatus.PENDING,
                customer_name_snapshot=customer.full_name,
                customer_phone_snapshot=customer.phone,
                idempotency_key=key,
                request_fingerprint=request_fingerprint(customer_id, cart.id, command),
                subtotal=subtotal,
                charges_total=fee,
                discount_total=money_zero(),
                delivery_fee=fee,
                total=money(subtotal + fee),
                items=items,
                branch_settings_snapshot=settings,
                local_details=local,
                pickup_details=pickup,
                delivery_details=delivery,
                schedule_calculation=schedule,
                history=(
                    StatusHistory(from_status=None, to_status=status, created_at=now),
                ),
                created_at=now,
                updated_at=now,
                confirmed_at=now if status == OrderStatus.WAITING else None,
            )
            order = await self._repository.create(order)
            await self._checkout.mark_checked_out(cart)
            await self._repository.commit()
            return order
        except OrderUniqueConflictError as error:
            await self._repository.rollback()
            existing = await self._repository.by_idempotency(customer_id, key)
            if existing is not None:
                return self._replay(existing, customer_id, command)
            raise OrderConflictError(
                "ORDER_ALREADY_CREATED"
                if error.constraint == "uq_orders_source_cart"
                else "ORDER_CONFLICT"
            ) from None
        except OrderRuleError:
            await self._repository.rollback()
            raise InvalidOrderDataError() from None
        except Exception:
            await self._repository.rollback()
            raise

    async def get(self, principal: Principal, order_id: UUID) -> Order:
        order = await self._repository.get_owned(customer_identity(principal), order_id)
        if order is None:
            raise OrderNotFoundError()
        return order

    async def list(self, principal: Principal, limit: int, offset: int) -> list[Order]:
        if not 1 <= limit <= 100 or offset < 0:
            raise InvalidOrderDataError()
        return await self._repository.list_owned(
            customer_identity(principal), limit, offset
        )

    async def confirm_cash_release(self, principal: Principal, order_id: UUID) -> Order:
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
        ):
            raise OrderPermissionDeniedError("ORDER_MANAGE")
        try:
            order = await self._repository.lock_order(order_id)
            if order is None:
                raise OrderNotFoundError()
            if not await self._authorization.has_permission(
                principal.user_id, order.branch_id, "ORDER_MANAGE"
            ):
                raise OrderPermissionDeniedError("ORDER_MANAGE")
            if (
                order.mode != OrderMode.LOCAL
                or order.payment_method_type != PaymentMethodType.CASH
                or order.status != OrderStatus.PENDING_CASH_CONFIRMATION
            ):
                raise OrderConflictError("CASH_RELEASE_NOT_ALLOWED")
            validate_transition(order, OrderStatus.WAITING)
            history = StatusHistory(
                from_status=order.status,
                to_status=OrderStatus.WAITING,
                changed_by_user_id=principal.user_id,
                reason="Cash order released; payment not recorded",
                created_at=self._clock(),
            )
            updated = await self._repository.release_cash(order, history)
            await self._repository.commit()
            return updated
        except Exception:
            await self._repository.rollback()
            raise


def money_zero():
    return Decimal("0.00")


class OrderSettingsService:
    def __init__(
        self, repository: OrderSettingsRepository, authorization: OrderAuthorization
    ) -> None:
        self._repository = repository
        self._authorization = authorization

    async def _require(self, principal: Principal, branch_id: UUID) -> None:
        if (
            principal.principal_type != PrincipalType.REGISTERED
            or principal.user_id is None
            or not await self._authorization.has_permission(
                principal.user_id, branch_id, "ORDER_SETTINGS_MANAGE"
            )
        ):
            raise OrderPermissionDeniedError("ORDER_SETTINGS_MANAGE")
        if not await self._repository.branch_is_active(branch_id):
            raise OrderResourceNotFoundError("BRANCH_NOT_FOUND")

    @asynccontextmanager
    async def _write(
        self, principal: Principal, branch_id: UUID
    ) -> AsyncIterator[None]:
        try:
            await self._require(principal, branch_id)
            yield
            await self._repository.commit()
        except OrderRuleError:
            await self._repository.rollback()
            raise InvalidOrderDataError() from None
        except Exception:
            await self._repository.rollback()
            raise

    async def get_settings(
        self, principal: Principal, branch_id: UUID
    ) -> BranchOrderSettings:
        await self._require(principal, branch_id)
        return await self._repository.get_settings(branch_id)

    async def update_settings(
        self, principal: Principal, branch_id: UUID, changes: dict
    ) -> BranchOrderSettings:
        async with self._write(principal, branch_id):
            before = await self._repository.get_settings(
                branch_id, lock=True, for_update=True
            )
            allowed = set(asdict(before)) - {"branch_id", "created_at", "updated_at"}
            if not changes or not changes.keys() <= allowed:
                raise InvalidOrderDataError()
            return await self._repository.save_settings(replace(before, **changes))

    async def list_tables(
        self, principal: Principal, branch_id: UUID
    ) -> list[RestaurantTable]:
        await self._require(principal, branch_id)
        return await self._repository.list_tables(branch_id)

    async def create_table(
        self, principal: Principal, branch_id: UUID, label: str
    ) -> RestaurantTable:
        async with self._write(principal, branch_id):
            return await self._repository.save_table(
                RestaurantTable(branch_id=branch_id, label=label.strip())
            )

    async def update_table(
        self, principal: Principal, branch_id: UUID, table_id: UUID, changes: dict
    ) -> RestaurantTable:
        async with self._write(principal, branch_id):
            before = await self._repository.get_table(branch_id, table_id)
            if before is None:
                raise OrderResourceNotFoundError("TABLE_NOT_FOUND")
            if not changes or not changes.keys() <= {
                "label",
                "is_active",
                "rotate_qr_token",
            }:
                raise InvalidOrderDataError()
            values = {
                name: value
                for name, value in changes.items()
                if name != "rotate_qr_token"
            }
            if "label" in values:
                values["label"] = values["label"].strip()
            if changes.get("rotate_qr_token"):
                values["qr_token"] = uuid4()
            return await self._repository.save_table(replace(before, **values))

    async def deactivate_table(
        self, principal: Principal, branch_id: UUID, table_id: UUID
    ) -> None:
        await self.update_table(principal, branch_id, table_id, {"is_active": False})

    async def list_zones(
        self, principal: Principal, branch_id: UUID
    ) -> list[DeliveryZone]:
        await self._require(principal, branch_id)
        return await self._repository.list_zones(branch_id)

    async def create_zone(
        self, principal: Principal, branch_id: UUID, values: dict
    ) -> DeliveryZone:
        async with self._write(principal, branch_id):
            values = self._zone_values(values)
            return await self._repository.save_zone(
                DeliveryZone(branch_id=branch_id, **values)
            )

    @staticmethod
    def _zone_values(values: dict) -> dict:
        if not values or not values.keys() <= {
            "name",
            "district",
            "is_free",
            "delivery_fee",
            "estimated_travel_minutes",
            "is_active",
        }:
            raise InvalidOrderDataError()
        return {
            name: value.strip() if name in {"name", "district"} else value
            for name, value in values.items()
        }

    async def update_zone(
        self, principal: Principal, branch_id: UUID, zone_id: UUID, changes: dict
    ) -> DeliveryZone:
        async with self._write(principal, branch_id):
            before = await self._repository.get_zone(branch_id, zone_id)
            if before is None:
                raise OrderResourceNotFoundError("DELIVERY_ZONE_NOT_FOUND")
            return await self._repository.save_zone(
                replace(before, **self._zone_values(changes))
            )

    async def deactivate_zone(
        self, principal: Principal, branch_id: UUID, zone_id: UUID
    ) -> None:
        await self.update_zone(principal, branch_id, zone_id, {"is_active": False})
