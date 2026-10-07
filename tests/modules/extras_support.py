"""Test-only stores; real identity/JWT fixtures are reused for HTTP tests."""

import asyncio
import copy
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.modules.auth.domain.models import Principal, PrincipalType
from app.modules.branches.application.customer_operations import CustomerBranchRecord
from app.modules.catalog.application.dtos import CategorySummary, PublicProduct
from app.modules.catalog.domain.models import ProductState
from app.modules.favorites.domain.models import Favorite
from app.modules.orders.application.customer_records import CustomerOrderRecord
from app.modules.promotions.domain.models import (
    CustomerReward,
    RouletteCampaign,
    RouletteParticipation,
    RoulettePrize,
    RouletteSpin,
)
from app.modules.receipts.application.ports import FiscalResult
from app.modules.receipts.domain.models import FiscalDocument, FiscalDocumentAttempt
from app.modules.reviews.domain.models import OrderReview
from app.shared.application.administration import (
    AdministrationConflict,
    AdministrativeBranch,
)

NOW = datetime(2026, 10, 7, 18, tzinfo=UTC)


def principal(guest=False, customer=None, user=None):
    return Principal(
        principal_type=PrincipalType.GUEST if guest else PrincipalType.REGISTERED,
        customer_id=customer or uuid4(),
        user_id=None if guest else user or uuid4(),
    )


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Audit:
    def __init__(self):
        self.records = []
        self.fail = False

    async def record(self, event):
        if self.fail:
            raise RuntimeError("TEST audit failure")
        self.records.append(event)


class Authorization:
    def __init__(self, admin, branch):
        self.admin, self.branch = admin, branch
        self.enabled = True
        self.permissions = {
            "REVIEW_VIEW",
            "RECEIPT_VIEW",
            "RECEIPT_MANAGE",
            "PROMOTION_VIEW",
            "PROMOTION_MANAGE",
            "PROMOTION_REDEEM",
        }

    async def has_permission(self, user, branch, permission):
        return (
            self.enabled
            and permission in self.permissions
            and user == self.admin
            and branch == self.branch
        )

    async def authorized_branches(self, user, permission, *, branch_id=None):
        return (
            (AdministrativeBranch(self.branch, "TEST", "America/Lima"),)
            if self.enabled
            and permission in self.permissions
            and user == self.admin
            and branch_id in {None, self.branch}
            else ()
        )


class Branches:
    def __init__(self, branch):
        self.branch = CustomerBranchRecord(branch, "America/Lima", True)

    async def customer_branch(self, branch_id, *, lock=False):
        return self.branch if branch_id == self.branch.id else None


def public_product(id_=None, available=True):
    return PublicProduct(
        id=id_ or uuid4(),
        category=CategorySummary(id=uuid4(), name="TEST", slug="test"),
        name="Original product",
        slug="original",
        description=None,
        effective_base_price=Decimal("8.50"),
        is_available=available,
        state=ProductState.AVAILABLE if available else ProductState.SOLD_OUT,
        allows_notes=True,
        primary_image=None,
        default_presentation=None,
        images=(),
        presentations=(),
        addons=(),
    )


class Catalog:
    def __init__(self, product=None):
        self.product = product or public_product()
        self.hidden = False
        self.exists = True
        self.batches = []

    async def product_exists(self, id_):
        return self.exists and id_ == self.product.id

    async def products(self, branch, ids):
        self.batches.append((branch, ids))
        return (
            {self.product.id: self.product}
            if not self.hidden and self.product.id in ids
            else {}
        )


class Orders:
    def __init__(self, customer, branch):
        self.order = CustomerOrderRecord(
            uuid4(),
            customer,
            branch,
            "LOCAL",
            "SERVED",
            "PAID",
            Decimal("47.00"),
            Decimal("47.00"),
            "PAID",
        )
        self.locks = []

    async def customer_order(self, customer, id_, *, lock=False):
        self.locks.append(lock)
        return (
            self.order
            if customer == self.order.customer_id and id_ == self.order.id
            else None
        )


class Favorites:
    def __init__(self):
        self.rows = {}
        self.commits = self.rollbacks = 0
        self.fail = False

    async def list_favorites(self, user, limit, offset):
        return [r for (u, _), r in self.rows.items() if u == user][
            offset : offset + limit
        ]

    async def add_favorite(self, user, product):
        key = (user, product)
        if key not in self.rows:
            self.rows[key] = Favorite(uuid4(), user, product, NOW)
        return self.rows[key]

    async def remove_favorite(self, user, product):
        self.rows.pop((user, product), None)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class Reviews:
    def __init__(self):
        self.rows = {}
        self.commits = self.rollbacks = 0
        self.scope = []

    async def find_review(self, customer, order):
        row = self.rows.get(order)
        return row if row and row.customer_id == customer else None

    async def create_review(self, order, customer, branch, rating, comment):
        if order in self.rows:
            raise AdministrationConflict("ORDER_ALREADY_REVIEWED", "Already reviewed")
        row = OrderReview(uuid4(), order, customer, branch, rating, comment, NOW, NOW)
        self.rows[order] = row
        return row

    async def branch_reviews(self, branch, rating, start, end, limit, offset):
        self.scope.append(branch)
        return [
            {
                "id": r.id,
                "order_id": r.order_id,
                "order_number": 1,
                "rating": r.rating,
                "comment": r.comment,
                "created_at": r.created_at,
            }
            for r in self.rows.values()
            if r.branch_id == branch
            and (rating is None or r.rating == rating)
            and (start is None or r.created_at >= start)
            and (end is None or r.created_at < end)
        ][offset : offset + limit]

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class Receipts:
    def __init__(self):
        self.docs = {}
        self.attempts = {}
        self.snapshot = None
        self.in_transaction = False
        self.commits = self.rollbacks = 0
        self.fail_finish = False

    def begin(self):
        self.in_transaction = True
        if self.snapshot is None:
            self.snapshot = copy.deepcopy((self.docs, self.attempts))

    async def customer_document(self, customer, order):
        return next(
            (
                d
                for d in self.docs.values()
                if d.customer_id == customer and d.order_id == order
            ),
            None,
        )

    async def branch_document(self, branch, id_, *, lock=False):
        if lock:
            self.begin()
        row = self.docs.get(id_)
        return row if row and row.branch_id == branch else None

    async def create_document(self, order, key, fingerprint, values, now):
        self.begin()
        doc = FiscalDocument(
            id=uuid4(),
            order_id=order.id,
            branch_id=order.branch_id,
            customer_id=order.customer_id,
            **values,
            status="PENDING",
            amount=order.paid_amount,
            currency_code="PEN",
            series=None,
            number=None,
            provider_code=None,
            provider_reference=None,
            request_key_hash=key,
            request_fingerprint=fingerprint,
            requested_at=now,
            issued_at=None,
            created_at=now,
            updated_at=now,
        )
        self.docs[doc.id] = doc
        return doc

    async def branch_documents(self, branch, status, type_, start, end, limit, offset):
        return [
            d
            for d in self.docs.values()
            if d.branch_id == branch
            and (status is None or d.status == status)
            and (type_ is None or d.document_type == type_)
            and (start is None or d.requested_at >= start)
            and (end is None or d.requested_at < end)
        ][offset : offset + limit]

    async def find_attempt(self, doc, key):
        return next(
            (
                a
                for a in self.attempts.values()
                if a.fiscal_document_id == doc and a.idempotency_key == key
            ),
            None,
        )

    async def active_attempt(self, doc):
        return next(
            (
                a
                for a in self.attempts.values()
                if a.fiscal_document_id == doc and a.status in {"CREATED", "PROCESSING"}
            ),
            None,
        )

    async def reserve_attempt(self, doc, key, provider, now):
        self.begin()
        attempt = FiscalDocumentAttempt(
            uuid4(), doc.id, key, provider, None, "PROCESSING", None, now, now, None
        )
        self.attempts[attempt.id] = attempt
        self.docs[doc.id] = replace(doc, status="PROCESSING", provider_code=provider)
        return attempt

    async def finish_attempt(self, doc, attempt, result, now):
        self.begin()
        current = self.attempts[attempt.id]
        if current.status in {"FAILED", "SUCCEEDED"}:
            return self.docs[doc.id]
        final = result.status in {"FAILED", "ISSUED"}
        self.attempts[attempt.id] = replace(
            current,
            status="SUCCEEDED" if result.status == "ISSUED" else result.status,
            completed_at=now if final else None,
            provider_reference=result.provider_reference,
        )
        if self.fail_finish:
            raise RuntimeError("TEST failed document update")
        updated = replace(
            self.docs[doc.id],
            status=result.status,
            series=result.series,
            number=result.number,
            provider_reference=result.provider_reference,
            issued_at=result.issued_at,
        )
        self.docs[doc.id] = updated
        return updated

    async def commit(self):
        self.commits += 1
        self.snapshot = None
        self.in_transaction = False

    async def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None:
            self.docs, self.attempts = self.snapshot
        self.snapshot = None
        self.in_transaction = False


class FiscalGateway:
    provider_code = "test_fiscal"

    def __init__(self, repo):
        self.repo = repo
        self.calls = self.lookups = 0
        self.unknown = False
        self.verified = True
        self.result_status = "ISSUED"

    def result(self, request):
        assert not self.repo.in_transaction
        return FiscalResult(
            document_id=request.document_id,
            attempt_id=request.attempt_id,
            provider_code=self.provider_code,
            status=self.result_status,
            verified=self.verified,
            amount=request.amount,
            currency_code="PEN",
            series="TEST",
            number=str(request.document_id),
            provider_reference=str(request.document_id),
            issued_at=NOW if self.result_status == "ISSUED" else None,
        )

    async def issue(self, request):
        self.calls += 1
        if self.unknown:
            raise TimeoutError("TEST unknown provider response")
        return self.result(request)

    async def lookup(self, request):
        self.lookups += 1
        return self.result(request)


class Random:
    def __init__(self, draw=0):
        self.value = draw
        self.calls = 0

    def draw(self):
        self.calls += 1
        return self.value


class PromotionState:
    def __init__(self):
        self.campaigns = {}
        self.prizes = {}
        self.participations = {}
        self.spins = {}
        self.rewards = {}
        self.lock = asyncio.Lock()
        self.fail_reward = False


class Promotions:
    def __init__(self, state=None):
        self.state = state or PromotionState()
        self.snapshot = None
        self.held = False
        self.commits = self.rollbacks = 0

    def begin(self):
        if self.snapshot is None:
            self.snapshot = copy.deepcopy(
                tuple(
                    getattr(self.state, k)
                    for k in (
                        "campaigns",
                        "prizes",
                        "participations",
                        "spins",
                        "rewards",
                    )
                )
            )

    async def hold(self):
        if not self.held:
            await self.state.lock.acquire()
            self.held = True
        self.begin()

    async def campaigns(self, branch, limit, offset):
        return [c for c in self.state.campaigns.values() if c.branch_id == branch][
            offset : offset + limit
        ]

    async def campaign(self, branch, id_, *, lock=False):
        if lock:
            await self.hold()
        row = self.state.campaigns.get(id_)
        return row if row and row.branch_id == branch else None

    async def active_campaign(self, branch, *, lock=False):
        if lock:
            await self.hold()
        return next(
            (
                c
                for c in self.state.campaigns.values()
                if c.branch_id == branch and c.is_active
            ),
            None,
        )

    async def create_campaign(self, branch, actor, values):
        self.begin()
        row = RouletteCampaign(
            id=uuid4(),
            branch_id=branch,
            created_by_user_id=actor,
            name=values["name"],
            terms_text=values["terms_text"],
            is_active=False,
            starts_at=values["starts_at"],
            ends_at=values.get("ends_at"),
            spin_cooldown_seconds=values["spin_cooldown_seconds"],
            max_spins_per_customer_per_day=values.get("max_spins_per_customer_per_day"),
            reward_validity_days=values.get("reward_validity_days"),
            version=1,
            created_at=NOW,
            updated_at=NOW,
        )
        self.state.campaigns[row.id] = row
        return row

    async def change_campaign(self, id_, values):
        self.begin()
        row = replace(
            self.state.campaigns[id_],
            **values,
            version=self.state.campaigns[id_].version + 1,
        )
        if row.is_active and any(
            c.is_active and c.branch_id == row.branch_id and c.id != id_
            for c in self.state.campaigns.values()
        ):
            raise AdministrationConflict(
                "ROULETTE_ACTIVE_CAMPAIGN_EXISTS", "Another campaign is active"
            )
        self.state.campaigns[id_] = row
        return row

    async def prizes(self, campaign):
        return sorted(
            [p for p in self.state.prizes.values() if p.campaign_id == campaign],
            key=lambda p: (p.sort_order, str(p.id)),
        )

    async def create_prize(self, campaign, values):
        self.begin()
        row = RoulettePrize(
            id=uuid4(),
            campaign_id=campaign,
            product_id=values["product_id"],
            display_name=values["display_name"],
            probability_bps=values["probability_bps"],
            is_active=values.get("is_active", True),
            max_awards=values.get("max_awards"),
            awarded_count=0,
            sort_order=values.get("sort_order", 0),
            created_at=NOW,
            updated_at=NOW,
        )
        self.state.prizes[row.id] = row
        return row

    async def change_prize(self, id_, values):
        self.begin()
        row = replace(self.state.prizes[id_], **values)
        self.state.prizes[id_] = row
        return row

    async def participation(self, campaign, customer, *, lock=False):
        key = (campaign, customer)
        if lock and key not in self.state.participations:
            self.begin()
            self.state.participations[key] = RouletteParticipation(
                uuid4(), campaign, customer, None, None, 0, NOW, NOW
            )
        return self.state.participations.get(key)

    async def find_spin(self, branch, customer, key):
        return next(
            (
                s
                for s in self.state.spins.values()
                if s.branch_id == branch
                and s.customer_id == customer
                and s.idempotency_key == key
            ),
            None,
        )

    async def spin_reward(self, spin):
        return next((r for r in self.state.rewards.values() if r.spin_id == spin), None)

    async def record_spin(self, campaign, customer, key, draw, prize, snapshot, now):
        self.begin()
        row = RouletteSpin(
            uuid4(),
            campaign.id,
            customer,
            campaign.branch_id,
            key,
            draw,
            "WIN" if prize else "NO_PRIZE",
            prize["id"] if prize else None,
            campaign.version,
            snapshot,
            now,
        )
        self.state.spins[row.id] = row
        return row

    async def advance_participation(self, participation, day, count, now):
        self.begin()
        self.state.participations[
            (participation.campaign_id, participation.customer_id)
        ] = replace(participation, day_key=day, spins_today=count, last_spin_at=now)

    async def award(self, spin, prize, expires):
        self.begin()
        original = self.state.prizes[prize["id"]]
        if (
            original.max_awards is not None
            and original.awarded_count >= original.max_awards
        ):
            raise AdministrationConflict(
                "ROULETTE_PRIZE_UNAVAILABLE", "Prize exhausted"
            )
        self.state.prizes[original.id] = replace(
            original, awarded_count=original.awarded_count + 1
        )
        if self.state.fail_reward:
            raise RuntimeError("TEST reward insert failure")
        row = CustomerReward(
            uuid4(),
            spin.id,
            spin.campaign_id,
            spin.customer_id,
            spin.branch_id,
            prize["id"],
            prize["product_id"],
            prize["product_name"],
            "AVAILABLE",
            spin.spun_at,
            expires,
            None,
            None,
            NOW,
            NOW,
        )
        self.state.rewards[row.id] = row
        return row

    async def rewards(self, customer, limit, offset):
        return [r for r in self.state.rewards.values() if r.customer_id == customer][
            offset : offset + limit
        ]

    async def branch_reward(self, branch, id_, *, lock=False):
        if lock:
            await self.hold()
        row = self.state.rewards.get(id_)
        return row if row and row.branch_id == branch else None

    async def redeem_reward(self, id_, actor, now):
        self.begin()
        row = replace(
            self.state.rewards[id_],
            status="REDEEMED",
            redeemed_at=now,
            redeemed_by_user_id=actor,
        )
        self.state.rewards[id_] = row
        return row

    async def commit(self):
        self.commits += 1
        self.snapshot = None
        if self.held:
            self.held = False
            self.state.lock.release()

    async def rollback(self):
        self.rollbacks += 1
        if self.snapshot is not None:
            for name, value in zip(
                ("campaigns", "prizes", "participations", "spins", "rewards"),
                self.snapshot,
                strict=True,
            ):
                setattr(self.state, name, value)
        self.snapshot = None
        if self.held:
            self.held = False
            self.state.lock.release()
