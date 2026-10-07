from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo


class InvalidDashboardPeriod(ValueError):
    """A calendar period outside the reporting contract."""


@dataclass(frozen=True)
class BranchPeriod:
    branch_id: UUID
    branch_name: str
    timezone: str
    from_date: date
    to_date: date
    start: datetime
    end: datetime


def branch_period(
    branch_id: UUID,
    name: str,
    timezone: str,
    now: datetime,
    first: date | None,
    last: date | None,
) -> BranchPeriod:
    if now.tzinfo is None or now.utcoffset() is None:
        raise InvalidDashboardPeriod("Reporting clock must be timezone-aware")
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    first = first or last or today
    last = last or first
    if last < first or (last - first).days >= 31:
        raise InvalidDashboardPeriod(
            "Period must contain between 1 and 31 calendar days"
        )
    try:
        end_date = last + timedelta(days=1)
        start = datetime.combine(first, time.min, zone).astimezone(UTC)
        end = datetime.combine(end_date, time.min, zone).astimezone(UTC)
    except OverflowError:
        raise InvalidDashboardPeriod("Period is out of range") from None
    return BranchPeriod(
        branch_id,
        name,
        timezone,
        first,
        last,
        start,
        end,
    )
