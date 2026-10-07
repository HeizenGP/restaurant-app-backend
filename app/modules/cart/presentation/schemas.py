from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.modules.cart.domain.models import MAX_QUANTITY, CartStatus, normalize_notes

MoneyOutput = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value, ".2f"), return_type=str, when_used="json"
    ),
]
Quantity = Annotated[int, Field(gt=0, le=MAX_QUANTITY, strict=True)]
Notes = Annotated[str, Field(max_length=1000)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyQueryRequest(RequestModel):
    """Cart identity never comes from query parameters."""


class EmptyBodyRequest(RequestModel):
    """Operations without input reject arbitrary identity or price fields."""


class CartCreateRequest(RequestModel):
    branch_id: UUID


class AddonSelectionRequest(RequestModel):
    addon_id: UUID
    option_ids: Annotated[list[UUID], Field(max_length=100)]


class ItemCreateRequest(RequestModel):
    product_id: UUID
    presentation_id: UUID
    quantity: Quantity
    notes: Notes | None = None
    addons: Annotated[list[AddonSelectionRequest], Field(max_length=100)] = Field(
        default_factory=list
    )

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return normalize_notes(value)


class ItemPatchRequest(RequestModel):
    quantity: Quantity | None = None
    presentation_id: UUID | None = None
    notes: Notes | None = None
    addons: Annotated[list[AddonSelectionRequest], Field(max_length=100)] | None = None

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str | None) -> str | None:
        return normalize_notes(value)

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if any(
            getattr(self, field) is None for field in self.model_fields_set - {"notes"}
        ):
            raise ValueError("Only notes can be null")
        return self


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SelectedOptionResponse(ResponseModel):
    id: UUID
    product_addon_id: UUID
    product_addon_option_id: UUID
    additional_price_snapshot: MoneyOutput
    created_at: datetime


class CartItemResponse(ResponseModel):
    id: UUID
    product_id: UUID
    presentation_id: UUID
    quantity: int
    notes: str | None
    selected_options: tuple[SelectedOptionResponse, ...]
    base_price_snapshot: MoneyOutput
    presentation_price_snapshot: MoneyOutput
    addons_price_snapshot: MoneyOutput
    unit_price_snapshot: MoneyOutput
    line_total: MoneyOutput
    created_at: datetime
    updated_at: datetime


class CartResponse(ResponseModel):
    id: UUID
    branch_id: UUID
    status: CartStatus
    items: tuple[CartItemResponse, ...]
    subtotal: MoneyOutput
    charges_total: MoneyOutput
    discount_total: MoneyOutput
    total: MoneyOutput
    item_count: int
    created_at: datetime
    updated_at: datetime
