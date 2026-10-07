from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.cart.domain.models import (
    Cart,
    CartItem,
    CartRuleError,
    CartStatus,
    CartTotals,
    normalize_notes,
    snapshot_money,
    validate_quantity,
)


def item(price: str = "20.00", quantity: int = 2) -> CartItem:
    return CartItem(
        cart_id=uuid4(),
        product_id=uuid4(),
        presentation_id=uuid4(),
        quantity=quantity,
        notes=None,
        base_price_snapshot=Decimal(price),
        presentation_price_snapshot=Decimal(price),
        addons_price_snapshot=Decimal("0.00"),
        unit_price_snapshot=Decimal(price),
    )


@pytest.mark.parametrize("quantity", [0, -1, 10001, True, 1.0, "2", None])
def test_quantity_rejects_invalid_and_technical_overflow(quantity):
    with pytest.raises(CartRuleError):
        validate_quantity(quantity)


@pytest.mark.parametrize(
    "value",
    [
        Decimal("-1"),
        Decimal("1.001"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("10000000000000000"),
        1.0,
        "1.00",
    ],
)
def test_money_requires_exact_bounded_decimal(value):
    with pytest.raises(CartRuleError):
        snapshot_money(value)


def test_totals_match_rf17_and_are_not_persisted():
    a, b = item(), item("15.50", 1)
    totals = CartTotals.from_items((a, b))
    assert a.line_total == Decimal("40.00")
    assert b.line_total == Decimal("15.50")
    assert totals.subtotal == totals.total == Decimal("55.50")
    assert totals.charges_total == totals.discount_total == Decimal("0.00")
    assert totals.item_count == 3
    assert CartTotals.from_items(()).total == Decimal("0.00")


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("   ", None),
        (" Sin cebolla ", "Sin cebolla"),
        ("Sin cebolla\nSin ají", "Sin cebolla\nSin ají"),
    ],
)
def test_notes_normalization(value, expected):
    assert normalize_notes(value) == expected


@pytest.mark.parametrize("value", ["x" * 1001, "secret\x00text", 123])
def test_notes_reject_invalid_data(value):
    with pytest.raises(CartRuleError):
        normalize_notes(value)


def test_snapshot_and_status_invariants():
    assert snapshot_money(Decimal("1.2")) == Decimal("1.20")
    assert Cart(customer_id=uuid4(), branch_id=uuid4()).status == CartStatus.ACTIVE
    with pytest.raises(CartRuleError):
        Cart(customer_id=uuid4(), branch_id=uuid4(), status="CHECKOUT")
    with pytest.raises(CartRuleError):
        replace(item(), unit_price_snapshot=Decimal("22.00"))
    with pytest.raises(CartRuleError):
        replace(
            item(),
            addons_price_snapshot=Decimal("2"),
            unit_price_snapshot=Decimal("22"),
        )
