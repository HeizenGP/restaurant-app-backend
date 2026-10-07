"""Test-only composition with deterministic clocks/random and injectable identities."""

from types import SimpleNamespace
from uuid import uuid4

from app.modules.favorites.application.services import FavoriteService
from app.modules.promotions.application.services import PromotionService
from app.modules.promotions.domain.models import RouletteCampaign, RoulettePrize
from app.modules.receipts.application.services import ReceiptService
from app.modules.reviews.application.services import ReviewService
from tests.modules.extras_support import (
    NOW,
    Audit,
    Authorization,
    Branches,
    Catalog,
    Clock,
    Favorites,
    FiscalGateway,
    Orders,
    Promotions,
    Random,
    Receipts,
    Reviews,
    principal,
)


def identities(customer=None, admin=None, branch=None):
    customer, admin, branch = (
        customer or principal(),
        admin or principal(),
        branch or uuid4(),
    )
    return SimpleNamespace(
        customer=customer,
        admin=admin,
        branch=branch,
        authorization=Authorization(admin.user_id, branch),
    )


def favorite_setup(customer=None, admin=None, branch=None):
    state = identities(customer, admin, branch)
    state.repo, state.catalog = Favorites(), Catalog()
    state.service = FavoriteService(state.repo, state.catalog)
    return state


def review_setup(customer=None, admin=None, branch=None):
    state = identities(customer, admin, branch)
    state.repo, state.orders = (
        Reviews(),
        Orders(state.customer.customer_id, state.branch),
    )
    state.service = ReviewService(state.repo, state.orders, state.authorization)
    return state


def receipt_setup(customer=None, admin=None, branch=None):
    state = identities(customer, admin, branch)
    state.repo, state.orders, state.audit, state.clock = (
        Receipts(),
        Orders(state.customer.customer_id, state.branch),
        Audit(),
        Clock(),
    )
    state.gateway = FiscalGateway(state.repo)
    state.service = ReceiptService(
        state.repo,
        state.orders,
        state.authorization,
        state.audit,
        state.gateway,
        state.clock,
    )
    return state


def promotion_setup(customer=None, admin=None, branch=None):
    state = identities(customer, admin, branch)
    state.repo, state.branches, state.catalog = (
        Promotions(),
        Branches(state.branch),
        Catalog(),
    )
    state.audit, state.random, state.clock = Audit(), Random(), Clock()
    state.campaign = RouletteCampaign(
        uuid4(),
        state.branch,
        "TEST Campaign",
        "Free promotional roulette. No purchase.",
        True,
        NOW,
        None,
        0,
        None,
        2,
        1,
        state.admin.user_id,
        NOW,
        NOW,
    )
    state.prize = RoulettePrize(
        uuid4(),
        state.campaign.id,
        state.catalog.product.id,
        "TEST Prize",
        1000,
        True,
        None,
        0,
        0,
        NOW,
        NOW,
    )
    state.repo.state.campaigns[state.campaign.id] = state.campaign
    state.repo.state.prizes[state.prize.id] = state.prize
    state.service = PromotionService(
        state.repo,
        state.branches,
        state.authorization,
        state.catalog,
        state.audit,
        state.random,
        state.clock,
    )
    return state
