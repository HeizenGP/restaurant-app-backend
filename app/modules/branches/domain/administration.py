import re
from datetime import time
from decimal import Decimal

BRANCH_FIELDS = {
    "name",
    "address_line",
    "district",
    "city",
    "department",
    "latitude",
    "longitude",
    "phone",
    "timezone",
}


def branch_fields(values: dict, *, creating: bool) -> dict:
    allowed = BRANCH_FIELDS | {"code", "hours"} if creating else BRANCH_FIELDS
    if not values or set(values) - allowed:
        raise ValueError("Unsupported branch fields")
    if (
        creating
        and not {"code", "name", "address_line", "district", "timezone", "hours"}
        <= values.keys()
    ):
        raise ValueError(
            "Branch creation requires identity, location, timezone and hours"
        )
    normalized = dict(values)
    for key, maximum in (
        ("name", 150),
        ("address_line", 1000),
        ("district", 120),
        ("city", 120),
        ("department", 120),
        ("timezone", 64),
    ):
        if key in values:
            value = values[key]
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value.strip()) > maximum
                or any(ord(c) < 32 for c in value)
            ):
                raise ValueError("Invalid branch text")
            normalized[key] = value.strip()
    for key, maximum in (("latitude", 90), ("longitude", 180)):
        if key in values and values[key] is not None:
            value = values[key]
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not -maximum <= value <= maximum
            ):
                raise ValueError("Invalid coordinates")
    if values.get("phone") is not None and not re.fullmatch(
        r"\+?[0-9]{9,15}", values["phone"]
    ):
        raise ValueError("Invalid phone")
    if creating:
        if not isinstance(values["code"], str):
            raise ValueError("Invalid branch code")
        code = values["code"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,39}", code):
            raise ValueError("Invalid branch code")
        normalized["code"] = code
        validate_hours(values["hours"])
    return normalized


def validate_hours(hours: list[dict]) -> None:
    if not isinstance(hours, list) or any(not isinstance(h, dict) for h in hours):
        raise ValueError("Invalid hours")
    if len(hours) != 7 or {h.get("day_of_week") for h in hours} != set(range(7)):
        raise ValueError("Provide seven distinct weekdays")
    for hour in hours:
        if (
            set(hour) != {"day_of_week", "open_time", "close_time", "is_closed"}
            or type(hour["day_of_week"]) is not int
            or type(hour["is_closed"]) is not bool
        ):
            raise ValueError("Invalid weekday")
        times = (hour["open_time"], hour["close_time"])
        if hour["is_closed"]:
            if any(value is not None for value in times):
                raise ValueError("Closed days must not specify times")
        elif any(
            not isinstance(value, time) or value.tzinfo is not None for value in times
        ):
            raise ValueError("Open days require local times")
