"""Bounded read models: one financial statement, no Orders loaded or summed in
Python."""

from dataclasses import asdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.domain.periods import BranchPeriod
from app.modules.orders.infrastructure.persistence.repositories import (
    SQLAlchemyOrderSettingsRepository,
)

ZERO = Decimal("0.00")
MODES = ("LOCAL", "PICKUP", "DELIVERY")


def dashboard_statement(periods: tuple[BranchPeriod, ...]):
    values = ",".join(
        f"(CAST(:b{i} AS uuid),CAST(:s{i} AS timestamptz),CAST(:e{i} AS timestamptz))"
        for i in range(len(periods))
    )
    params = {
        key: value
        for i, p in enumerate(periods)
        for key, value in ((f"b{i}", p.branch_id), (f"s{i}", p.start), (f"e{i}", p.end))
    }
    sql = (
        """
    WITH bounds(branch_id,start_at,end_at) AS (VALUES """
        + values
        + """),
    paid AS (
        SELECT o.id,o.branch_id,o.mode,o.status,p.amount,p.paid_at
        FROM bounds b JOIN orders o ON o.branch_id=b.branch_id
        JOIN payments p ON p.order_id=o.id
        WHERE p.status='PAID' AND p.paid_at>=b.start_at AND p.paid_at<b.end_at
    ), sales AS (
        SELECT branch_id,mode,SUM(amount) gross,COUNT(*) paid_count
        FROM paid GROUP BY branch_id,mode
    ), returns AS (
        SELECT o.branch_id,o.mode,SUM(r.amount) refunded
        FROM bounds b JOIN orders o ON o.branch_id=b.branch_id
        JOIN refunds r ON r.order_id=o.id
        WHERE r.status='REFUNDED' AND r.refunded_at>=b.start_at AND
        r.refunded_at<b.end_at
        GROUP BY o.branch_id,o.mode
    ), volume AS (
        SELECT o.branch_id,o.mode,COUNT(*) orders_count
        FROM bounds b JOIN orders o ON o.branch_id=b.branch_id
        WHERE o.created_at>=b.start_at AND o.created_at<b.end_at
        GROUP BY o.branch_id,o.mode
    ), eligible_items AS (
        SELECT i.product_id,i.product_name_snapshot,i.quantity,p.paid_at,
            i.created_at,i.id
        FROM paid p JOIN order_items i ON i.order_id=p.id
        WHERE p.status<>'CANCELLED'
    ), top_totals AS (
        SELECT i.product_id,SUM(i.quantity)::bigint quantity
        FROM eligible_items i
        GROUP BY i.product_id ORDER BY quantity DESC,i.product_id LIMIT 10
    ), top_names AS (
        SELECT DISTINCT ON (i.product_id) i.product_id,
            i.product_name_snapshot product_name
        FROM eligible_items i JOIN top_totals t ON t.product_id=i.product_id
        ORDER BY i.product_id,i.paid_at DESC,i.created_at DESC,i.id DESC
    ), top AS (
        SELECT t.product_id,n.product_name,t.quantity
        FROM top_totals t JOIN top_names n ON n.product_id=t.product_id
    )
    SELECT 'financial' kind,b.branch_id,m.mode,
        COALESCE(s.gross,0)::numeric gross,COALESCE(r.refunded,0)::numeric refunded,
        COALESCE(v.orders_count,0)::bigint orders_count,COALESCE(s.paid_count,
        0)::bigint paid_count,
        NULL::uuid product_id,NULL::text product_name,NULL::bigint quantity
    FROM bounds b CROSS JOIN (VALUES ('LOCAL'),('PICKUP'),('DELIVERY')) m(mode)
    LEFT JOIN sales s ON s.branch_id=b.branch_id AND s.mode=m.mode
    LEFT JOIN returns r ON r.branch_id=b.branch_id AND r.mode=m.mode
    LEFT JOIN volume v ON v.branch_id=b.branch_id AND v.mode=m.mode
    UNION ALL
    SELECT 'top',NULL::uuid,NULL::text,NULL::numeric,NULL::numeric,NULL::bigint,
    NULL::bigint,
        product_id,product_name,quantity FROM top
    ORDER BY kind,quantity DESC,product_id,branch_id,mode
    """
    )
    return text(sql), params


def empty_totals() -> dict:
    return {
        "gross_sales": ZERO,
        "refunded_amount": ZERO,
        "net_sales": ZERO,
        "orders_count": 0,
        "paid_orders_count": 0,
    }


class SQLAlchemyAdministrationReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dashboard(self, periods: tuple[BranchPeriod, ...]) -> dict:
        statement, params = dashboard_statement(periods)
        rows = (await self.session.execute(statement, params)).mappings()
        summary = empty_totals()
        modes = {mode: {"mode": mode, **empty_totals()} for mode in MODES}
        branches = {
            p.branch_id: {
                "branch_id": p.branch_id,
                "branch_name": p.branch_name,
                "period": asdict(p),
                **empty_totals(),
            }
            for p in periods
        }
        products = []
        for row in rows:
            if row["kind"] == "top":
                products.append(
                    {
                        key: row[key]
                        for key in ("product_id", "product_name", "quantity")
                    }
                )
                continue
            totals = {
                "gross_sales": row["gross"],
                "refunded_amount": row["refunded"],
                "net_sales": row["gross"] - row["refunded"],
                "orders_count": row["orders_count"],
                "paid_orders_count": row["paid_count"],
            }
            # Only bounded aggregate rows (3 per authorized branch), never source
            # orders.
            for target in (summary, modes[row["mode"]], branches[row["branch_id"]]):
                for key, value in totals.items():
                    target[key] += value
        return {
            "currency_code": "PEN",
            "summary": summary,
            "sales_by_mode": list(modes.values()),
            "sales_by_branch": list(branches.values()),
            "top_products": products,
        }

    async def configuration(self, branch_id: UUID) -> dict:
        branch = (
            (
                await self.session.execute(
                    text(
                        "SELECT id,code,name,timezone,is_active FROM branches "
                        "WHERE id=:id"
                    ),
                    {"id": branch_id},
                )
            )
            .mappings()
            .one()
        )
        hours = (
            (
                await self.session.execute(
                    text(
                        "SELECT day_of_week,open_time,close_time,is_closed FROM "
                        "branch_hours WHERE branch_id=:id ORDER BY day_of_week"
                    ),
                    {"id": branch_id},
                )
            )
            .mappings()
            .all()
        )
        counts = (
            (
                await self.session.execute(
                    text("""
            SELECT (SELECT COUNT(*) FROM restaurant_tables WHERE branch_id=:id)
            table_count,
                (SELECT COUNT(*) FROM delivery_zones WHERE branch_id=:id OR
                branch_id IS NULL) delivery_zone_count,
                (SELECT COUNT(*) FROM branch_products WHERE branch_id=:id)
                configured_product_count
        """),
                    {"id": branch_id},
                )
            )
            .mappings()
            .one()
        )
        settings = await SQLAlchemyOrderSettingsRepository(self.session).get_settings(
            branch_id
        )
        return {
            "branch": dict(branch),
            "hours": [dict(h) for h in hours],
            "order_settings": asdict(settings),
            "table_count": counts["table_count"],
            "delivery_zone_count": counts["delivery_zone_count"],
            "catalog_summary": {
                "configured_product_count": counts["configured_product_count"]
            },
        }
