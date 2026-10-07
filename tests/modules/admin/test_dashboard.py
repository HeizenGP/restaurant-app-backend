import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.admin.domain.periods import branch_period
from app.modules.admin.infrastructure.read_repository import (
    SQLAlchemyAdministrationReadRepository,
    dashboard_statement,
)
from app.modules.admin.presentation.schemas import DashboardResponse
from tests.modules.admin.test_domain import NOW


def period(zone="America/Lima"):
    return branch_period(uuid4(), "Branch", zone, NOW, None, None)


@pytest.mark.parametrize(
    "gross,refund,expected",
    [
        ("0.00", "0.00", "0.00"),
        ("100.10", "20.05", "80.05"),
        ("0.00", "50.00", "-50.00"),
        ("0.10", "0.00", "0.10"),
    ],
)
def test_decimal_totals_include_negative_net_and_never_float(gross, refund, expected):
    p = period()
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = [
        {
            "kind": "financial",
            "branch_id": p.branch_id,
            "mode": "LOCAL",
            "gross": Decimal(gross),
            "refunded": Decimal(refund),
            "orders_count": 2,
            "paid_count": 1,
        }
    ]
    session.execute.return_value = result
    report = asyncio.run(
        SQLAlchemyAdministrationReadRepository(session).dashboard((p,))
    )
    assert report["summary"]["net_sales"] == Decimal(expected)
    assert all(
        isinstance(report["summary"][key], Decimal)
        for key in ("gross_sales", "refunded_amount", "net_sales")
    )
    session.execute.assert_awaited_once()
    session.commit.assert_not_called()
    rendered = DashboardResponse(**report).model_dump(mode="json")
    assert isinstance(rendered["summary"]["gross_sales"], str)
    assert len(report["sales_by_mode"]) == 3


def test_zero_report_contains_all_scoped_branches_and_modes():
    a, b = period(), period("Asia/Tokyo")
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = []
    session.execute.return_value = result
    report = asyncio.run(
        SQLAlchemyAdministrationReadRepository(session).dashboard((a, b))
    )
    assert report["summary"]["orders_count"] == 0
    assert report["summary"]["gross_sales"] == Decimal("0.00")
    assert len(report["sales_by_branch"]) == 2 and len(report["sales_by_mode"]) == 3
    assert report["top_products"] == []


def test_one_statement_aggregates_branch_and_mode_without_cross_multiplication():
    a, b = period(), period("Asia/Tokyo")
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value = [
        {
            "kind": "financial",
            "branch_id": a.branch_id,
            "mode": "LOCAL",
            "gross": Decimal("20.00"),
            "refunded": Decimal("5.00"),
            "orders_count": 2,
            "paid_count": 1,
        },
        {
            "kind": "financial",
            "branch_id": b.branch_id,
            "mode": "PICKUP",
            "gross": Decimal("30.00"),
            "refunded": Decimal("2.00"),
            "orders_count": 1,
            "paid_count": 1,
        },
        {
            "kind": "top",
            "product_id": uuid4(),
            "product_name": "Historical",
            "quantity": 3,
        },
    ]
    session.execute.return_value = result
    report = asyncio.run(
        SQLAlchemyAdministrationReadRepository(session).dashboard((a, b))
    )
    assert report["summary"]["net_sales"] == Decimal("43.00")
    assert report["summary"]["orders_count"] == 3
    assert report["sales_by_branch"][0]["net_sales"] == Decimal("15.00")
    assert report["sales_by_branch"][1]["net_sales"] == Decimal("28.00")
    assert report["top_products"][0]["product_name"] == "Historical"
    session.execute.assert_awaited_once()


def test_sql_uses_financial_dates_independently_and_historical_product_ids():
    a, b = period(), period("Asia/Tokyo")
    statement, params = dashboard_statement((a, b))
    sql = str(statement)
    for clause in (
        "p.status='PAID'",
        "p.paid_at>=b.start_at",
        "p.paid_at<b.end_at",
        "r.status='REFUNDED'",
        "r.refunded_at>=b.start_at",
        "r.refunded_at<b.end_at",
        "o.created_at>=b.start_at",
        "o.created_at<b.end_at",
        "SUM(i.quantity)",
        "GROUP BY i.product_id",
        "quantity DESC,i.product_id LIMIT 10",
        "i.product_name_snapshot",
        "p.status<>'CANCELLED'",
    ):
        assert clause in sql
    assert "FROM products" not in sql and "JOIN products" not in sql
    assert params["b0"] == a.branch_id and params["b1"] == b.branch_id
    assert params["s0"] != params["s1"]
    assert (
        "p.paid_at>=b.start_at" not in sql.split("returns AS")[1].split("volume AS")[0]
    )
    assert "SELECT *" not in sql and "UPDATE " not in sql and "DELETE " not in sql
    assert "ARRAY_AGG" not in sql
    assert "DISTINCT ON (i.product_id)" in sql
