from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.modules.auth.presentation.dependencies import CurrentPrincipal
from app.modules.catalog.application.dtos import (
    AddonCreate,
    BranchProductConfig,
    CatalogChanges,
    CategoryCreate,
    ImageCreate,
    OptionCreate,
    PresentationCreate,
    ProductCreate,
)
from app.modules.catalog.presentation.dependencies import CatalogServiceDependency
from app.modules.catalog.presentation.schemas import (
    AddonCreateRequest,
    AddonPatchRequest,
    AddonResponse,
    AdminProductDetailResponse,
    BranchProductConfigResponse,
    BranchProductRequest,
    BranchProductResponse,
    CategoryCreateRequest,
    CategoryPatchRequest,
    CategoryResponse,
    ImageCreateRequest,
    ImagePatchRequest,
    ImageResponse,
    MenuCategoryResponse,
    OptionCreateRequest,
    OptionPatchRequest,
    OptionResponse,
    PatchRequest,
    PresentationCreateRequest,
    PresentationPatchRequest,
    PresentationResponse,
    ProductCreateRequest,
    ProductPatchRequest,
    ProductResponse,
    PublicProductResponse,
)
from app.presentation.errors import ErrorResponse

ERRORS = {
    code: {"model": ErrorResponse} for code in (400, 401, 403, 404, 409, 422, 503)
}
router = APIRouter(prefix="/catalog", tags=["catalog"], responses=ERRORS)
admin_router = APIRouter(
    prefix="/admin/catalog", tags=["admin-catalog"], responses=ERRORS
)
BranchQuery = Annotated[UUID, Query()]


def changes(payload: PatchRequest) -> CatalogChanges:
    values = payload.model_dump(exclude_unset=True)
    if "url" in values:
        values["url"] = str(values["url"])
    return CatalogChanges(values)


@router.get("/menu", response_model=list[MenuCategoryResponse])
async def menu(
    branch_id: BranchQuery, service: CatalogServiceDependency
) -> list[MenuCategoryResponse]:
    return [
        MenuCategoryResponse.model_validate(category)
        for category in await service.menu(branch_id)
    ]


@router.get("/products/{product_id}", response_model=PublicProductResponse)
async def product_detail(
    product_id: UUID, branch_id: BranchQuery, service: CatalogServiceDependency
) -> PublicProductResponse:
    return PublicProductResponse.model_validate(
        await service.product_detail(branch_id, product_id)
    )


@admin_router.get("/products/{product_id}", response_model=AdminProductDetailResponse)
async def admin_product(
    product_id: UUID, principal: CurrentPrincipal, service: CatalogServiceDependency
) -> AdminProductDetailResponse:
    aggregate = await service.admin_product(principal, product_id)
    return AdminProductDetailResponse(
        product=ProductResponse.model_validate(aggregate.product),
        category=CategoryResponse.model_validate(aggregate.category),
        images=tuple(ImageResponse.model_validate(image) for image in aggregate.images),
        presentations=tuple(
            PresentationResponse.model_validate(p) for p in aggregate.presentations
        ),
        addons=tuple(AddonResponse.model_validate(addon) for addon in aggregate.addons),
        options=tuple(
            OptionResponse.model_validate(option) for option in aggregate.options
        ),
        is_publicable=bool(
            aggregate.product.is_active
            and aggregate.product.deleted_at is None
            and aggregate.category.is_active
            and aggregate.category.deleted_at is None
            and any(
                p.is_active and p.deleted_at is None for p in aggregate.presentations
            )
        ),
    )


@admin_router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    principal: CurrentPrincipal, service: CatalogServiceDependency
) -> list[CategoryResponse]:
    return [
        CategoryResponse.model_validate(entity)
        for entity in await service.list_categories(principal)
    ]


@admin_router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    payload: CategoryCreateRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> CategoryResponse:
    return CategoryResponse.model_validate(
        await service.create_category(principal, CategoryCreate(**payload.model_dump()))
    )


@admin_router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    payload: CategoryPatchRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> CategoryResponse:
    return CategoryResponse.model_validate(
        await service.update_category(principal, category_id, changes(payload))
    )


@admin_router.delete(
    "/categories/{category_id}", status_code=204, response_class=Response
)
async def archive_category(
    category_id: UUID, principal: CurrentPrincipal, service: CatalogServiceDependency
) -> Response:
    await service.archive_category(principal, category_id)
    return Response(status_code=204)


@admin_router.get("/products", response_model=list[ProductResponse])
async def list_products(
    principal: CurrentPrincipal, service: CatalogServiceDependency
) -> list[ProductResponse]:
    return [
        ProductResponse.model_validate(entity)
        for entity in await service.list_products(principal)
    ]


@admin_router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    payload: ProductCreateRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> ProductResponse:
    return ProductResponse.model_validate(
        await service.create_product(principal, ProductCreate(**payload.model_dump()))
    )


@admin_router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    payload: ProductPatchRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> ProductResponse:
    return ProductResponse.model_validate(
        await service.update_product(principal, product_id, changes(payload))
    )


@admin_router.delete("/products/{product_id}", status_code=204, response_class=Response)
async def archive_product(
    product_id: UUID, principal: CurrentPrincipal, service: CatalogServiceDependency
) -> Response:
    await service.archive_product(principal, product_id)
    return Response(status_code=204)


@admin_router.post(
    "/products/{product_id}/images", response_model=ImageResponse, status_code=201
)
async def create_image(
    product_id: UUID,
    payload: ImageCreateRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> ImageResponse:
    return ImageResponse.model_validate(
        await service.create_image(
            principal,
            product_id,
            ImageCreate(
                url=str(payload.url),
                alt_text=payload.alt_text,
                sort_order=payload.sort_order,
                is_primary=payload.is_primary,
            ),
        )
    )


@admin_router.patch(
    "/products/{product_id}/images/{image_id}", response_model=ImageResponse
)
async def update_image(
    product_id: UUID,
    image_id: UUID,
    payload: ImagePatchRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> ImageResponse:
    return ImageResponse.model_validate(
        await service.update_image(principal, product_id, image_id, changes(payload))
    )


@admin_router.delete(
    "/products/{product_id}/images/{image_id}", status_code=204, response_class=Response
)
async def archive_image(
    product_id: UUID,
    image_id: UUID,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> Response:
    await service.archive_image(principal, product_id, image_id)
    return Response(status_code=204)


@admin_router.post(
    "/products/{product_id}/presentations",
    response_model=PresentationResponse,
    status_code=201,
)
async def create_presentation(
    product_id: UUID,
    payload: PresentationCreateRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> PresentationResponse:
    return PresentationResponse.model_validate(
        await service.create_presentation(
            principal, product_id, PresentationCreate(**payload.model_dump())
        )
    )


@admin_router.patch(
    "/products/{product_id}/presentations/{presentation_id}",
    response_model=PresentationResponse,
)
async def update_presentation(
    product_id: UUID,
    presentation_id: UUID,
    payload: PresentationPatchRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> PresentationResponse:
    return PresentationResponse.model_validate(
        await service.update_presentation(
            principal, product_id, presentation_id, changes(payload)
        )
    )


@admin_router.delete(
    "/products/{product_id}/presentations/{presentation_id}",
    status_code=204,
    response_class=Response,
)
async def archive_presentation(
    product_id: UUID,
    presentation_id: UUID,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> Response:
    await service.archive_presentation(principal, product_id, presentation_id)
    return Response(status_code=204)


@admin_router.post(
    "/products/{product_id}/addons", response_model=AddonResponse, status_code=201
)
async def create_addon(
    product_id: UUID,
    payload: AddonCreateRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> AddonResponse:
    return AddonResponse.model_validate(
        await service.create_addon(
            principal, product_id, AddonCreate(**payload.model_dump())
        )
    )


@admin_router.patch(
    "/products/{product_id}/addons/{addon_id}", response_model=AddonResponse
)
async def update_addon(
    product_id: UUID,
    addon_id: UUID,
    payload: AddonPatchRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> AddonResponse:
    return AddonResponse.model_validate(
        await service.update_addon(principal, product_id, addon_id, changes(payload))
    )


@admin_router.delete(
    "/products/{product_id}/addons/{addon_id}", status_code=204, response_class=Response
)
async def archive_addon(
    product_id: UUID,
    addon_id: UUID,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> Response:
    await service.archive_addon(principal, product_id, addon_id)
    return Response(status_code=204)


@admin_router.post(
    "/products/{product_id}/addons/{addon_id}/options",
    response_model=OptionResponse,
    status_code=201,
)
async def create_option(
    product_id: UUID,
    addon_id: UUID,
    payload: OptionCreateRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> OptionResponse:
    return OptionResponse.model_validate(
        await service.create_option(
            principal, product_id, addon_id, OptionCreate(**payload.model_dump())
        )
    )


@admin_router.patch(
    "/products/{product_id}/addons/{addon_id}/options/{option_id}",
    response_model=OptionResponse,
)
async def update_option(
    product_id: UUID,
    addon_id: UUID,
    option_id: UUID,
    payload: OptionPatchRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> OptionResponse:
    return OptionResponse.model_validate(
        await service.update_option(
            principal, product_id, addon_id, option_id, changes(payload)
        )
    )


@admin_router.delete(
    "/products/{product_id}/addons/{addon_id}/options/{option_id}",
    status_code=204,
    response_class=Response,
)
async def archive_option(
    product_id: UUID,
    addon_id: UUID,
    option_id: UUID,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> Response:
    await service.archive_option(principal, product_id, addon_id, option_id)
    return Response(status_code=204)


@admin_router.get(
    "/branches/{branch_id}/products/{product_id}",
    response_model=BranchProductConfigResponse,
)
async def get_branch_product(
    branch_id: UUID,
    product_id: UUID,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> BranchProductConfigResponse:
    return BranchProductConfigResponse.model_validate(
        await service.get_branch_product(principal, branch_id, product_id)
    )


@admin_router.put(
    "/branches/{branch_id}/products/{product_id}", response_model=BranchProductResponse
)
async def upsert_branch_product(
    branch_id: UUID,
    product_id: UUID,
    payload: BranchProductRequest,
    principal: CurrentPrincipal,
    service: CatalogServiceDependency,
) -> BranchProductResponse:
    return BranchProductResponse.model_validate(
        await service.upsert_branch_product(
            principal,
            branch_id,
            product_id,
            BranchProductConfig(**payload.model_dump()),
        )
    )
