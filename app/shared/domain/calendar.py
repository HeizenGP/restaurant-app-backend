from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def calendar_bounds(first: date | None, last: date | None, timezone: str):
    if first and last and first > last:
        raise ValueError("Date range is inverted")
    try:
        zone = ZoneInfo(timezone)
        start = (
            datetime.combine(first, time.min, zone).astimezone(UTC) if first else None
        )
        end = (
            datetime.combine(last + timedelta(days=1), time.min, zone).astimezone(UTC)
            if last
            else None
        )
    except (OverflowError, ValueError):
        raise ValueError("Date range is invalid") from None
    return start, end
