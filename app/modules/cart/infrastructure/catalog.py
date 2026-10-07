from uuid import UUID

from app.modules.cart.application.dtos import (
    AddonSelection,
    ValidatedOption,
    ValidatedSelection,
)
from app.modules.cart.application.errors import (
    CartProductUnavailableError,
    CartSelectionInvalidError,
)
from app.modules.catalog.application.dtos import AddonSelection as CatalogAddonSelection
from app.modules.catalog.application.errors import (
    CatalogNotFoundError,
    InvalidSelectionError,
    ProductNotAvailableError,
)
from app.modules.catalog.application.ports import CatalogRepository
from app.modules.catalog.application.services import CatalogService


class CatalogSelectionAdapter:
    """Calls the existing use case; Catalog owns validation and all pricing."""

    def __init__(self, service: CatalogService, repository: CatalogRepository) -> None:
        self._service = service
        self._repository = repository

    async def branch_is_active(self, branch_id: UUID) -> bool:
        return await self._repository.branch_is_active(branch_id)

    async def validate_selection(
        self,
        branch_id: UUID,
        product_id: UUID,
        presentation_id: UUID,
        addons: tuple[AddonSelection, ...],
        notes: str | None,
    ) -> ValidatedSelection:
        try:
            result = await self._service.validate_selection(
                branch_id,
                product_id,
                presentation_id,
                tuple(CatalogAddonSelection(a.addon_id, a.option_ids) for a in addons),
                notes,
            )
        except ProductNotAvailableError:
            raise CartProductUnavailableError() from None
        except (CatalogNotFoundError, InvalidSelectionError):
            raise CartSelectionInvalidError() from None
        return ValidatedSelection(
            product_id=result.product_id,
            branch_id=result.branch_id,
            presentation_id=result.presentation_id,
            base_price=result.base_price,
            presentation_price=result.presentation_price,
            addons_price=result.addons_price,
            unit_price=result.unit_price,
            allows_notes=result.allows_notes,
            options=tuple(
                ValidatedOption(
                    option.addon_id, option.option_id, option.additional_price
                )
                for option in result.selected_options
            ),
        )
