from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from app.modules.promotions.domain.models import (
    CustomerReward,
    RouletteCampaign,
    RouletteParticipation,
    RoulettePrize,
)

CAMPAIGN_FIELDS = {
    "name",
    "terms_text",
    "starts_at",
    "ends_at",
    "spin_cooldown_seconds",
    "max_spins_per_customer_per_day",
    "reward_validity_days",
    "is_active",
}
PRIZE_FIELDS = {
    "product_id",
    "display_name",
    "probability_bps",
    "is_active",
    "max_awards",
    "sort_order",
}


def plain_text(value, maximum):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > maximum
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise ValueError("Invalid configuration text")
    if "<" in value or ">" in value:
        raise ValueError("Configuration must be plain text")
    return value.strip()


def campaign_values(values: dict, *, creating: bool) -> dict:
    if not values or set(values) - CAMPAIGN_FIELDS:
        raise ValueError("Unsupported campaign fields")
    normalized = dict(values)
    if (
        creating
        and not {"name", "terms_text", "starts_at", "spin_cooldown_seconds"}
        <= values.keys()
    ):
        raise ValueError("Missing campaign configuration")
    for key, maximum in (("name", 150), ("terms_text", 10000)):
        if key in normalized:
            normalized[key] = plain_text(normalized[key], maximum)
    for key in ("starts_at", "ends_at"):
        if key in values and (values[key] is not None or key == "starts_at"):
            value = values[key]
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError("Campaign times must be timezone-aware")
            normalized[key] = value.astimezone(UTC)
    for key, minimum in (
        ("spin_cooldown_seconds", 0),
        ("max_spins_per_customer_per_day", 1),
        ("reward_validity_days", 1),
    ):
        if key in values and (
            values[key] is not None or key == "spin_cooldown_seconds"
        ):
            if type(values[key]) is not int or not minimum <= values[key] <= 2147483647:
                raise ValueError("Invalid frequency or validity")
    if "is_active" in values and type(values["is_active"]) is not bool:
        raise ValueError("Invalid activity flag")
    if creating and values.get("is_active", False):
        raise ValueError("Create a draft, configure prizes, then activate")
    return normalized


def campaign_window(campaign: RouletteCampaign) -> None:
    if campaign.ends_at is not None and campaign.ends_at <= campaign.starts_at:
        raise ValueError("Campaign end must follow start")


def prize_values(values: dict) -> dict:
    if not values or set(values) - PRIZE_FIELDS:
        raise ValueError("Unsupported prize fields")
    result = dict(values)
    if "display_name" in values:
        result["display_name"] = plain_text(values["display_name"], 150)
    if "product_id" in values and not isinstance(values["product_id"], UUID):
        raise ValueError("Product must be a UUID")
    if "probability_bps" in values and (
        type(values["probability_bps"]) is not int
        or not 0 <= values["probability_bps"] <= 10000
    ):
        raise ValueError("Probability must be integer basis points")
    for key in ("max_awards", "sort_order"):
        if key in values and values[key] is not None:
            if type(values[key]) is not int or not 0 <= values[key] <= 2147483647:
                raise ValueError("Invalid prize limit or sort order")
    if "is_active" in values and type(values["is_active"]) is not bool:
        raise ValueError("Invalid activity flag")
    return result


def effective_prizes(prizes: list[RoulettePrize], products: dict) -> list[dict]:
    result = []
    cursor = 0
    for prize in sorted(prizes, key=lambda p: (p.sort_order, str(p.id))):
        product = products.get(prize.product_id)
        available = bool(
            prize.is_active
            and product is not None
            and product.is_available
            and (prize.max_awards is None or prize.awarded_count < prize.max_awards)
        )
        width = prize.probability_bps if prize.is_active else 0
        result.append(
            {
                "id": prize.id,
                "product_id": prize.product_id,
                "display_name": prize.display_name,
                "probability_bps": prize.probability_bps,
                "effective_probability_bps": width if available else 0,
                "is_available": available,
                "start": cursor,
                "end": cursor + width,
                "product_name": product.name if product else None,
            }
        )
        cursor += width
    if cursor > 10000:
        raise ValueError("Total configured probability exceeds 10000")
    return result


def select_prize(draw: int, prizes: list[dict]):
    if type(draw) is not int or not 0 <= draw < 10000:
        raise ValueError("Random source must return integer 0..9999")
    return next(
        (p for p in prizes if p["start"] <= draw < p["end"] and p["is_available"]), None
    )


def participation_state(
    campaign: RouletteCampaign,
    participation: RouletteParticipation | None,
    now: datetime,
    timezone: str,
):
    zone = ZoneInfo(timezone)
    day = now.astimezone(zone).date()
    count = (
        participation.spins_today
        if participation and participation.day_key == day
        else 0
    )
    next_at = (
        participation.last_spin_at + timedelta(seconds=campaign.spin_cooldown_seconds)
        if participation and participation.last_spin_at
        else None
    )
    cooldown = next_at is not None and now < next_at
    daily = (
        campaign.max_spins_per_customer_per_day is not None
        and count >= campaign.max_spins_per_customer_per_day
    )
    if daily:
        reset = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(
            UTC
        )
        next_at = max(next_at, reset) if next_at else reset
    return day, count, next_at, cooldown, daily


def reward_view(reward: CustomerReward, now: datetime) -> CustomerReward:
    return (
        replace(reward, status="EXPIRED")
        if reward.status == "AVAILABLE"
        and reward.expires_at
        and reward.expires_at <= now
        else reward
    )
