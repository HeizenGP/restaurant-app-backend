import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PlainSerializer,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.catalog.domain.models import ProductState

Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]
Slug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
]
AltText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
]
MoneyInput = Annotated[
    Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
]
MoneyOutput = Annotated[
    Decimal,
    PlainSerializer(
        lambda value: format(value, ".2f"), return_type=str, when_used="json"
    ),
]
SortOrder = Annotated[int, Field(ge=0, le=2147483647, strict=True)]
ImageUrl = Annotated[HttpUrl, Field(max_length=2048)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def validate_text(cls, value: object) -> object:
        if isinstance(value, str) and any(
            unicodedata.category(c).startswith("C") for c in value
        ):
            raise ValueError("Control characters are not allowed")
        if isinstance(value, HttpUrl) and (
            value.username is not None or value.password is not None
        ):
            raise ValueError("Image URL must not contain credentials")
        return value


class PatchRequest(RequestModel):
    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        for field in self.model_fields_set - {"description", "alt_text"}:
            if getattr(self, field) is None:
                raise ValueError("This field cannot be null")
        return self


class CategoryCreateRequest(RequestModel):
    name: Name
    slug: Slug
    description: Description | None = None
    sort_order: SortOrder = 0
    is_active: StrictBool = True


class CategoryPatchRequest(PatchRequest):
    name: Name | None = None
    slug: Slug | None = None
    description: Description | None = None
    sort_order: SortOrder | None = None
    is_active: StrictBool | None = None


class ProductCreateRequest(RequestModel):
    category_id: UUID
    name: Name
    slug: Slug
    description: Description | None = None
    base_price: MoneyInput
    allows_notes: StrictBool = True
    sort_order: SortOrder = 0
    is_active: StrictBool = True


class ProductPatchRequest(PatchRequest):
    category_id: UUID | None = None
    name: Name | None = None
    slug: Slug | None = None
    description: Description | None = None
    base_price: MoneyInput | None = None
    allows_notes: StrictBool | None = None
    sort_order: SortOrder | None = None
    is_active: StrictBool | None = None


class ImageCreateRequest(RequestModel):
    url: ImageUrl
    alt_text: AltText | None = None
    sort_order: SortOrder = 0
    is_primary: StrictBool = False


class ImagePatchRequest(PatchRequest):
    url: ImageUrl | None = None
    alt_text: AltText | None = None
    sort_order: SortOrder | None = None
    is_primary: StrictBool | None = None


class PresentationCreateRequest(RequestModel):
    name: Name
    price_delta: MoneyInput
    is_default: StrictBool = False
    is_active: StrictBool = True
    sort_order: SortOrder = 0


class PresentationPatchRequest(PatchRequest):
    name: Name | None = None
    price_delta: MoneyInput | None = None
    is_default: StrictBool | None = None
    is_active: StrictBool | None = None
    sort_order: SortOrder | None = None


class AddonCreateRequest(RequestModel):
    name: Name
    is_required: StrictBool = False
    min_select: SortOrder = 0
    max_select: Annotated[int, Field(ge=1, le=2147483647, strict=True)] = 1
    sort_order: SortOrder = 0
    is_active: StrictBool = True

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.min_select > self.max_select:
            raise ValueError("min_select must not exceed max_select")
        return self


class AddonPatchRequest(PatchRequest):
    name: Name | None = None
    is_required: StrictBool | None = None
    min_select: SortOrder | None = None
    max_select: Annotated[int, Field(ge=1, le=2147483647, strict=True)] | None = None
    sort_order: SortOrder | None = None
    is_active: StrictBool | None = None

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if (
            self.min_select is not None
            and self.max_select is not None
            and self.min_select > self.max_select
        ):
            raise ValueError("min_select must not exceed max_select")
        return self


class OptionCreateRequest(RequestModel):
    name: Name
    additional_price: MoneyInput
    sort_order: SortOrder = 0
    is_active: StrictBool = True


class OptionPatchRequest(PatchRequest):
    name: Name | None = None
    additional_price: MoneyInput | None = None
    sort_order: SortOrder | None = None
    is_active: StrictBool | None = None


class BranchProductRequest(RequestModel):
    is_available: StrictBool
    price_override: MoneyInput | None = None


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CategorySummaryResponse(ResponseModel):
    id: UUID
    name: str
    slug: str


class PublicImageResponse(ResponseModel):
    id: UUID
    url: str
    alt_text: str | None
    sort_order: int
    is_primary: bool


class PublicPresentationResponse(ResponseModel):
    id: UUID
    name: str
    price_delta: MoneyOutput
    effective_price: MoneyOutput
    is_default: bool


class PublicOptionResponse(ResponseModel):
    id: UUID
    name: str
    additional_price: MoneyOutput


class PublicAddonResponse(ResponseModel):
    id: UUID
    name: str
    is_required: bool
    min_select: int
    max_select: int
    options: tuple[PublicOptionResponse, ...]


class PublicProductResponse(ResponseModel):
    id: UUID
    category: CategorySummaryResponse
    name: str
    slug: str
    description: str | None
    effective_base_price: MoneyOutput
    is_available: bool
    state: ProductState
    allows_notes: bool
    primary_image: PublicImageResponse | None
    default_presentation: PublicPresentationResponse | None
    images: tuple[PublicImageResponse, ...]
    presentations: tuple[PublicPresentationResponse, ...]
    addons: tuple[PublicAddonResponse, ...]


class MenuCategoryResponse(ResponseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    products: tuple[PublicProductResponse, ...]


class AdminEntityResponse(ResponseModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class CategoryResponse(AdminEntityResponse):
    name: str
    slug: str
    description: str | None
    sort_order: int
    is_active: bool


class ProductResponse(AdminEntityResponse):
    category_id: UUID
    name: str
    slug: str
    description: str | None
    base_price: MoneyOutput
    allows_notes: bool
    sort_order: int
    is_active: bool


class ImageResponse(AdminEntityResponse):
    product_id: UUID
    url: str
    alt_text: str | None
    sort_order: int
    is_primary: bool


class PresentationResponse(AdminEntityResponse):
    product_id: UUID
    name: str
    price_delta: MoneyOutput
    is_default: bool
    is_active: bool
    sort_order: int


class AddonResponse(AdminEntityResponse):
    product_id: UUID
    name: str
    is_required: bool
    min_select: int
    max_select: int
    sort_order: int
    is_active: bool


class OptionResponse(AdminEntityResponse):
    product_addon_id: UUID
    name: str
    additional_price: MoneyOutput
    sort_order: int
    is_active: bool


class AdminProductDetailResponse(ResponseModel):
    product: ProductResponse
    category: CategoryResponse
    images: tuple[ImageResponse, ...]
    presentations: tuple[PresentationResponse, ...]
    addons: tuple[AddonResponse, ...]
    options: tuple[OptionResponse, ...]
    is_publicable: bool


class BranchProductResponse(ResponseModel):
    id: UUID
    branch_id: UUID
    product_id: UUID
    is_available: bool
    price_override: MoneyOutput | None
    created_at: datetime
    updated_at: datetime


class BranchProductConfigResponse(ResponseModel):
    is_available: bool
    price_override: MoneyOutput | None
