"""Reuse actual AuthService/JWT verification; override business storage only."""

from types import SimpleNamespace

import pytest

from app.modules.favorites.presentation.router import get_favorite_service
from app.modules.promotions.presentation.router import get_promotion_service
from app.modules.receipts.infrastructure.fiscal_gateway import (
    UnconfiguredFiscalDocumentGateway,
)
from app.modules.receipts.presentation.router import get_receipt_service
from app.modules.reviews.presentation.router import get_review_service
from tests.modules.extras_factories import (
    favorite_setup,
    promotion_setup,
    receipt_setup,
    review_setup,
)


@pytest.fixture
def extras_api(api):
    arguments = (api.setup.customer, api.setup.admin, api.setup.branch)
    s = SimpleNamespace(
        api=api,
        client=api.client,
        headers=api.headers,
        favorites=favorite_setup(*arguments),
        reviews=review_setup(*arguments),
        receipts=receipt_setup(*arguments),
        promotions=promotion_setup(*arguments),
    )
    # The default HTTP fixture keeps the production unconfigured fiscal behavior.
    s.receipts.service.gateway = UnconfiguredFiscalDocumentGateway()

    def provide(service):
        return lambda: service

    for dependency, service in (
        (get_favorite_service, s.favorites.service),
        (get_review_service, s.reviews.service),
        (get_receipt_service, s.receipts.service),
        (get_promotion_service, s.promotions.service),
    ):
        api.client.app.dependency_overrides[dependency] = provide(service)
    yield s
