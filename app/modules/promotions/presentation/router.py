from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from app.modules.auth.domain.models import Principal
from app.modules.auth.presentation.dependencies import (
    CurrentRegisteredUser,
    SessionDependency,
    get_current_customer,
)
from app.modules.branches.infrastructure.customer_operations import (
    SQLAlchemyCustomerBranchReader,
)
from app.modules.branches.infrastructure.persistence.repositories import (
    SQLAlchemyBranchRepository,
)
from app.modules.catalog.presentation.dependencies import CatalogServiceDependency
from app.modules.promotions.application.services import PromotionService
from app.modules.promotions.infrastructure.catalog import CatalogPrizeGateway
from app.modules.promotions.infrastructure.persistence.repositories import (
    SQLAlchemyPromotionRepository,
)
from app.modules.promotions.infrastructure.random_source import SecretsRandomSource
from app.modules.promotions.presentation.schemas import (
    CampaignDetail,
    CampaignResponse,
    CreateCampaign,
    CreatePrize,
    Pagination,
    PatchCampaign,
    PatchPrize,
    PrizeResponse,
    RewardResponse,
    RouletteQuery,
    RouletteResponse,
    SpinRequest,
    SpinResponse,
)
from app.presentation.errors import ErrorResponse
from app.shared.infrastructure.audit.repository import SQLAlchemyAuditRecorder

ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
router = APIRouter(prefix="/promotions", tags=["promotions"], responses=ERRORS)
admin_router = APIRouter(
    prefix="/admin/promotions/branches", tags=["admin promotions"], responses=ERRORS
)
CurrentCustomer = Annotated[Principal, Depends(get_current_customer)]
Key = Annotated[
    str, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{1,128}$")
]


def get_promotion_service(
    session: SessionDependency, catalog: CatalogServiceDependency
):
    return PromotionService(
        SQLAlchemyPromotionRepository(session),
        SQLAlchemyCustomerBranchReader(session),
        SQLAlchemyBranchRepository(session),
        CatalogPrizeGateway(catalog),
        SQLAlchemyAuditRecorder(session),
        SecretsRandomSource(),
    )


Service = Annotated[PromotionService, Depends(get_promotion_service)]


@router.get("/roulette", response_model=RouletteResponse)
async def roulette(
    principal: CurrentCustomer,
    service: Service,
    query: Annotated[RouletteQuery, Query()],
):
    return await service.roulette(principal, query.branch_id)


@router.post("/roulette/spins", status_code=201, response_model=SpinResponse)
async def spin(
    body: SpinRequest, key: Key, principal: CurrentCustomer, service: Service
):
    return await service.spin(principal, body.branch_id, key)


@router.get("/rewards", response_model=list[RewardResponse])
async def rewards(
    principal: CurrentCustomer, service: Service, query: Annotated[Pagination, Query()]
):
    return await service.rewards(principal, **query.model_dump())


CAMPAIGNS = "/{branch_id}/roulette/campaigns"


@admin_router.get(CAMPAIGNS, response_model=list[CampaignResponse])
async def campaigns(
    branch_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
    query: Annotated[Pagination, Query()],
):
    return await service.list_campaigns(principal, branch_id, **query.model_dump())


@admin_router.post(CAMPAIGNS, status_code=201, response_model=CampaignResponse)
async def create_campaign(
    branch_id: UUID,
    body: CreateCampaign,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.create_campaign(principal, branch_id, body.model_dump())


@admin_router.get(CAMPAIGNS + "/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(
    branch_id: UUID,
    campaign_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.get_campaign(principal, branch_id, campaign_id)


@admin_router.patch(CAMPAIGNS + "/{campaign_id}", response_model=CampaignResponse)
async def patch_campaign(
    branch_id: UUID,
    campaign_id: UUID,
    body: PatchCampaign,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.change_campaign(
        principal, branch_id, campaign_id, body.model_dump(exclude_unset=True)
    )


@admin_router.post(
    CAMPAIGNS + "/{campaign_id}/deactivate", response_model=CampaignResponse
)
async def deactivate_campaign(
    branch_id: UUID,
    campaign_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.change_campaign(
        principal, branch_id, campaign_id, {"is_active": False}
    )


@admin_router.post(
    CAMPAIGNS + "/{campaign_id}/prizes", status_code=201, response_model=PrizeResponse
)
async def create_prize(
    branch_id: UUID,
    campaign_id: UUID,
    body: CreatePrize,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.change_prize(
        principal, branch_id, campaign_id, body.model_dump()
    )


@admin_router.patch(
    CAMPAIGNS + "/{campaign_id}/prizes/{prize_id}", response_model=PrizeResponse
)
async def patch_prize(
    branch_id: UUID,
    campaign_id: UUID,
    prize_id: UUID,
    body: PatchPrize,
    principal: CurrentRegisteredUser,
    service: Service,
):
    return await service.change_prize(
        principal, branch_id, campaign_id, body.model_dump(exclude_unset=True), prize_id
    )


@admin_router.delete(CAMPAIGNS + "/{campaign_id}/prizes/{prize_id}", status_code=204)
async def deactivate_prize(
    branch_id: UUID,
    campaign_id: UUID,
    prize_id: UUID,
    principal: CurrentRegisteredUser,
    service: Service,
):
    await service.change_prize(
        principal, branch_id, campaign_id, {"is_active": False}, prize_id
    )
    return Response(status_code=204)


@admin_router.post(
    "/{branch_id}/rewards/{reward_id}/redeem", response_model=RewardResponse
)
async def redeem(
    branch_id: UUID, reward_id: UUID, principal: CurrentRegisteredUser, service: Service
):
    return await service.redeem(principal, branch_id, reward_id)
