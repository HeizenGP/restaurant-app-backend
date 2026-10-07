from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    SessionDependency,
    get_current_customer,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.orders.infrastructure.customer_records import (
    SQLAlchemyCustomerOrderReader,
)
from app.modules.reviews.application.services import ReviewService
from app.modules.reviews.domain.models import review_values
from app.modules.reviews.infrastructure.persistence.repositories import (
    SQLAlchemyReviewRepository,
)
from app.presentation.errors import ErrorResponse

ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/orders", tags=["order reviews"], responses=ERRORS)
admin_router = APIRouter(
    prefix="/admin/reviews/branches", tags=["admin reviews"], responses=ERRORS
)
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]


def get_review_service(session: SessionDependency):
    return ReviewService(
        SQLAlchemyReviewRepository(session),
        SQLAlchemyCustomerOrderReader(session),
        SQLAlchemyBranchRepository(session),
    )


Service = Annotated[ReviewService, Depends(get_review_service)]


class CreateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5, strict=True)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def plain_text(cls, value):
        return review_values(1, value)[1]


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    branch_id: UUID
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


class AdminReviewResponse(BaseModel):
    id: UUID
    order_id: UUID
    order_number: int
    rating: int
    comment: str | None
    created_at: datetime


class ReviewQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int | None = Field(default=None, ge=1, le=5)
    from_date: date | None = None
    to_date: date | None = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


@router.post("/{order_id}/review", status_code=201, response_model=ReviewResponse)
async def create_review(
    order_id: UUID, body: CreateReview, principal: CurrentCustomer, service: Service
):
    return await service.create(principal, order_id, **body.model_dump())


@router.get("/{order_id}/review", response_model=ReviewResponse)
async def get_review(order_id: UUID, principal: CurrentCustomer, service: Service):
    return await service.get(principal, order_id)


@admin_router.get("/{branch_id}", response_model=list[AdminReviewResponse])
async def branch_reviews(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
    query: Annotated[ReviewQuery, Query()],
):
    return await service.list(principal, branch_id, **query.model_dump())
