from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.branches.presentation.schemas import BranchHourResponse
from app.modules.orders.presentation.schemas import SettingsResponse


class DashboardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch_id: UUID | None = None
    from_date: date | None = None
    to_date: date | None = None


class TotalsResponse(BaseModel):
    gross_sales: Decimal
    refunded_amount: Decimal
    net_sales: Decimal
    orders_count: int
    paid_orders_count: int


class ModeSales(TotalsResponse):
    mode: Literal["LOCAL", "PICKUP", "DELIVERY"]


class PeriodResponse(BaseModel):
    branch_id: UUID
    branch_name: str
    timezone: str
    from_date: date
    to_date: date
    start: datetime
    end: datetime


class BranchSales(TotalsResponse):
    branch_id: UUID
    branch_name: str
    period: PeriodResponse


class TopProduct(BaseModel):
    product_id: UUID
    product_name: str
    quantity: int


class DashboardResponse(BaseModel):
    currency_code: Literal["PEN"]
    summary: TotalsResponse
    sales_by_mode: list[ModeSales]
    sales_by_branch: list[BranchSales]
    top_products: list[TopProduct]


class ConfigurationBranch(BaseModel):
    id: UUID
    code: str
    name: str
    timezone: str
    is_active: bool


class CatalogConfigurationSummary(BaseModel):
    configured_product_count: int


class ConfigurationResponse(BaseModel):
    branch: ConfigurationBranch
    hours: list[BranchHourResponse]
    order_settings: SettingsResponse
    table_count: int
    delivery_zone_count: int
    catalog_summary: CatalogConfigurationSummary
