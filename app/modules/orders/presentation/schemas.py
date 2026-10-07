from datetime import datetime
from decimal import Decimal
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.cart.presentation.schemas import MoneyOutput
from app.modules.orders.domain.models import (
    OrderMode,
    OrderStatus,
    PaymentMethodType,
    PaymentStatus,
)

MoneyInput = Annotated[
    Decimal, Field(ge=0, max_digits=18, decimal_places=2, allow_inf_nan=False)
]
Minutes = Annotated[int, Field(ge=0, le=1440, strict=True)]
Label = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
ZoneName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def no_control_characters(cls, value: object) -> object:
        if isinstance(value, str) and any(ord(char) < 32 for char in value):
            raise ValueError("Control characters are not allowed")
        return value


class EmptyRequest(RequestModel):
    pass


class LocalCreateRequest(RequestModel):
    mode: Literal["LOCAL"]
    table_qr_token: UUID
    payment_method: PaymentMethodType


class PickupCreateRequest(RequestModel):
    mode: Literal["PICKUP"]
    requested_pickup_at: AwareDatetime


class DeliveryCreateRequest(RequestModel):
    mode: Literal["DELIVERY"]
    address_id: UUID


OrderCreateRequest = LocalCreateRequest | PickupCreateRequest | DeliveryCreateRequest


class PaginationRequest(RequestModel):
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0, le=2147483647)] = 0


class PatchRequest(RequestModel):
    nullable_fields: ClassVar[set[str]] = set()

    @model_validator(mode="after")
    def nonempty_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(
            getattr(self, name) is None
            for name in self.model_fields_set - self.nullable_fields
        ):
            raise ValueError("This field cannot be null")
        return self


class SettingsPatchRequest(PatchRequest):
    cash_payment_requires_confirmation: StrictBool | None = None
    delivery_minimum_order: MoneyInput | None = None
    default_prep_minutes: Annotated[int, Field(ge=1, le=1440, strict=True)] | None = (
        None
    )
    queue_delay_per_order_minutes: Minutes | None = None
    pickup_buffer_minutes: Minutes | None = None
    delivery_default_travel_minutes: Minutes | None = None
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = (
        None
    )


class TableCreateRequest(RequestModel):
    label: Label


class TablePatchRequest(PatchRequest):
    label: Label | None = None
    is_active: StrictBool | None = None
    rotate_qr_token: StrictBool | None = None


class ZoneCreateRequest(RequestModel):
    name: ZoneName
    district: ZoneName
    is_free: StrictBool = False
    delivery_fee: MoneyInput
    estimated_travel_minutes: Minutes | None = None
    is_active: StrictBool = True


class ZonePatchRequest(PatchRequest):
    nullable_fields: ClassVar[set[str]] = {"estimated_travel_minutes"}
    name: ZoneName | None = None
    district: ZoneName | None = None
    is_free: StrictBool | None = None
    delivery_fee: MoneyInput | None = None
    estimated_travel_minutes: Minutes | None = None
    is_active: StrictBool | None = None


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SettingsResponse(ResponseModel):
    branch_id: UUID
    cash_payment_requires_confirmation: bool
    delivery_minimum_order: MoneyOutput
    default_prep_minutes: int
    queue_delay_per_order_minutes: int
    pickup_buffer_minutes: int
    delivery_default_travel_minutes: int
    timezone: str
    created_at: datetime
    updated_at: datetime


class TableResponse(ResponseModel):
    id: UUID
    branch_id: UUID
    label: str
    qr_token: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ZoneResponse(ResponseModel):
    id: UUID
    branch_id: UUID | None
    name: str
    district: str
    is_free: bool
    delivery_fee: MoneyOutput
    estimated_travel_minutes: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AddonOptionResponse(ResponseModel):
    id: UUID
    product_addon_id: UUID
    product_addon_option_id: UUID
    addon_name_snapshot: str
    option_name_snapshot: str
    additional_price_snapshot: MoneyOutput


class OrderItemResponse(ResponseModel):
    id: UUID
    product_id: UUID
    presentation_id: UUID
    product_name_snapshot: str
    presentation_name_snapshot: str
    quantity: int
    notes: str | None
    base_price_snapshot: MoneyOutput
    presentation_price_snapshot: MoneyOutput
    addons_price_snapshot: MoneyOutput
    unit_price_snapshot: MoneyOutput
    line_total_snapshot: MoneyOutput
    addon_options: tuple[AddonOptionResponse, ...]
    created_at: datetime


class LocalDetailsResponse(ResponseModel):
    table_id: UUID = Field(validation_alias="restaurant_table_id")
    table_label: str = Field(validation_alias="table_label_snapshot")
    payment_choice: PaymentMethodType
    cash_confirmation_required: bool = Field(
        validation_alias="cash_confirmation_required_snapshot"
    )


class PickupDetailsResponse(ResponseModel):
    requested_pickup_at: datetime
    calculated_kitchen_release_at: datetime
    estimated_ready_at: datetime
    pickup_name: str = Field(validation_alias="pickup_name_snapshot")
    pickup_phone: str = Field(validation_alias="pickup_phone_snapshot")


class DeliveryDetailsResponse(ResponseModel):
    delivery_zone_id: UUID
    delivery_zone_name_snapshot: str
    recipient_name_snapshot: str
    recipient_phone_snapshot: str
    address_line_snapshot: str
    reference_text_snapshot: str | None
    district_snapshot: str
    city_snapshot: str
    department_snapshot: str
    latitude_snapshot: Decimal | None
    longitude_snapshot: Decimal | None
    delivery_fee_snapshot: MoneyOutput
    estimated_delivery_at: datetime


class ScheduleResponse(ResponseModel):
    queue_depth: int
    base_prep_minutes: int
    queue_delay_minutes: int
    buffer_minutes: int
    travel_minutes: int
    calculated_release_at: datetime | None
    estimated_ready_at: datetime


class HistoryResponse(ResponseModel):
    from_status: OrderStatus | None
    to_status: OrderStatus
    reason: str | None
    created_at: datetime


class OrderResponse(ResponseModel):
    id: UUID
    order_number: int
    source_cart_id: UUID
    branch_id: UUID
    mode: OrderMode
    status: OrderStatus
    payment_method_type: PaymentMethodType
    payment_status: PaymentStatus
    customer_name_snapshot: str
    customer_phone_snapshot: str
    items: tuple[OrderItemResponse, ...]
    subtotal: MoneyOutput
    charges_total: MoneyOutput
    discount_total: MoneyOutput
    delivery_fee: MoneyOutput
    total: MoneyOutput
    local_details: LocalDetailsResponse | None
    pickup_details: PickupDetailsResponse | None
    delivery_details: DeliveryDetailsResponse | None
    schedule_calculation: ScheduleResponse | None
    history: tuple[HistoryResponse, ...]
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
