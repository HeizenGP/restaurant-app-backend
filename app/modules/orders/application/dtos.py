from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from app.modules.orders.domain.models import OrderMode, PaymentMethodType


@dataclass(frozen=True, kw_only=True)
class OrderCreate:
    mode: OrderMode
    payment_method: PaymentMethodType = PaymentMethodType.ONLINE
    table_qr_token: UUID | None = None
    requested_pickup_at: datetime | None = None
    address_id: UUID | None = None


@dataclass(frozen=True, kw_only=True)
class CustomerSnapshot:
    id: UUID
    full_name: str
    phone: str


@dataclass(frozen=True, kw_only=True)
class AddressSnapshot:
    id: UUID
    recipient_name: str
    recipient_phone: str
    address_line: str
    reference_text: str | None
    district: str
    city: str
    department: str
    latitude: Decimal | None
    longitude: Decimal | None


@dataclass(frozen=True)
class BranchHours:
    hours: tuple[tuple[int, time | None, time | None, bool], ...]


@dataclass(frozen=True)
class PreparationEstimate:
    queue_depth: int
    base_prep_minutes: int
    queue_delay_minutes: int

    @property
    def total_minutes(self) -> int:
        return self.base_prep_minutes + self.queue_delay_minutes
