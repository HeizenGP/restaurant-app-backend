from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.admin.domain.periods import InvalidDashboardPeriod, branch_period
from app.modules.branches.domain.administration import branch_fields, validate_hours
from app.modules.branches.presentation.admin_schemas import (
    CreateBranchRequest,
    HoursInput,
    UpdateBranchRequest,
)
from app.modules.customers.domain.administration import customer_fields
from app.modules.customers.presentation.admin_schemas import (
    CreateAdministrativeCustomer,
    UpdateAdministrativeCustomer,
)

NOW = datetime(2026, 10, 7, 2, tzinfo=UTC)


def closed_hours():
    return [
        {"day_of_week": day, "open_time": None, "close_time": None, "is_closed": True}
        for day in range(7)
    ]


def branch_values():
    return {
        "code": "new",
        "name": "New",
        "address_line": "Test street",
        "district": "Test",
        "timezone": "America/Lima",
        "hours": closed_hours(),
    }


@pytest.mark.parametrize(
    "zone,local_day,start_hour",
    [("America/Lima", 6, 5), ("UTC", 7, 0), ("Asia/Tokyo", 7, 15)],
)
def test_today_is_each_branch_local_day(zone, local_day, start_hour):
    period = branch_period(uuid4(), "Branch", zone, NOW, None, None)
    assert period.from_date == date(2026, 10, local_day)
    assert period.start.hour == start_hour
    assert period.end - period.start == timedelta(days=1)


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_dst_uses_local_calendar_midnights(day, hours):
    period = branch_period(uuid4(), "Branch", "America/New_York", NOW, day, day)
    assert period.end - period.start == timedelta(hours=hours)


@pytest.mark.parametrize(
    "first,last",
    [
        (date(2026, 10, 8), date(2026, 10, 7)),
        (date(2026, 1, 1), date(2026, 2, 1)),
        (date.max, date.max),
    ],
)
def test_invalid_period_is_pure_rule_error(first, last):
    with pytest.raises(InvalidDashboardPeriod):
        branch_period(uuid4(), "Branch", "UTC", NOW, first, last)


def test_exactly_31_days_and_half_open_upper_bound():
    period = branch_period(
        uuid4(), "Branch", "America/Lima", NOW, date(2026, 1, 1), date(2026, 1, 31)
    )
    assert period.start == datetime(2026, 1, 1, 5, tzinfo=UTC)
    assert period.end == datetime(2026, 2, 1, 5, tzinfo=UTC)


def test_naive_reporting_clock_is_rejected():
    with pytest.raises(InvalidDashboardPeriod):
        branch_period(uuid4(), "Branch", "UTC", NOW.replace(tzinfo=None), None, None)


def test_minimum_date_utc_conversion_overflow_is_validation_error():
    with pytest.raises(InvalidDashboardPeriod):
        branch_period(uuid4(), "Branch", "Asia/Tokyo", NOW, date.min, date.min)


@pytest.mark.parametrize("hours", [None, "invalid", [None] * 7])
def test_malformed_hours_are_pure_validation_errors(hours):
    with pytest.raises(ValueError):
        validate_hours(hours)


@pytest.mark.parametrize("day", [True, "0", 0.0])
def test_api_weekday_requires_integer(day):
    hours = closed_hours()
    hours[0]["day_of_week"] = day
    with pytest.raises(ValidationError):
        HoursInput(hours=hours)


def test_full_week_and_overnight_are_supported():
    hours = closed_hours()
    hours[0] = {
        "day_of_week": 0,
        "open_time": time(22),
        "close_time": time(2),
        "is_closed": False,
    }
    validate_hours(hours)
    assert HoursInput(hours=hours).hours[0].close_time == time(2)
    assert CreateBranchRequest(**branch_values()).code == "NEW"


@pytest.mark.parametrize(
    "patch",
    [
        {"is_closed": False},
        {"open_time": time(12)},
        {"day_of_week": True},
        {"close_time": "10:00"},
        {"is_closed": None},
        {"id": uuid4()},
    ],
)
def test_invalid_hours_are_rejected_in_domain(patch):
    hours = closed_hours()
    hours[0].update(patch)
    with pytest.raises(ValueError):
        validate_hours(hours)


@pytest.mark.parametrize("count", [0, 1, 6, 8])
def test_hours_must_have_exactly_seven_entries(count):
    with pytest.raises((ValueError, ValidationError)):
        HoursInput(hours=(closed_hours() * 2)[:count])


@pytest.mark.parametrize(
    "patch",
    [
        {"code": "bad space"},
        {"code": None},
        {"is_active": False},
        {"id": uuid4()},
        {"latitude": Decimal("NaN")},
        {"longitude": Decimal("181")},
        {"name": "bad\nname"},
        {"timezone": None},
    ],
)
def test_branch_create_rejects_unknown_or_invalid_fields(patch):
    with pytest.raises(ValueError):
        branch_fields(branch_values() | patch, creating=True)


@pytest.mark.parametrize(
    "key", ["code", "is_active", "deleted_at", "id", "created_at", "hours"]
)
def test_branch_patch_cannot_mutate_identity_or_lifecycle(key):
    with pytest.raises(ValidationError):
        UpdateBranchRequest(**{key: "injected"})


@pytest.mark.parametrize(
    "patch",
    [
        {"phone": "+51912345678"},
        {"user_id": uuid4()},
        {"is_guest": False},
        {"phone_verified_at": NOW},
        {"created_by_branch_id": uuid4()},
        {"order_count": 3},
        {"password": "secret"},
    ],
)
def test_customer_patch_has_no_identity_or_server_fields(patch):
    with pytest.raises(ValidationError):
        UpdateAdministrativeCustomer(**patch)
    with pytest.raises(ValueError):
        customer_fields(patch, creating=False)


@pytest.mark.parametrize(
    "patch",
    [
        {"full_name": ""},
        {"full_name": "bad\nname"},
        {"phone": "123"},
        {"email": "invalid"},
        {"email": "a b@test"},
        {"id": uuid4()},
        {"email": "a" * 255 + "@test"},
    ],
)
def test_customer_creation_validated_in_application_domain(patch):
    with pytest.raises(ValueError):
        customer_fields(
            {"full_name": "Test", "phone": "+51912345678"} | patch, creating=True
        )


def test_guest_contacts_are_not_verification_and_nulls_are_explicit():
    values = customer_fields(
        {"full_name": " Test ", "phone": "+51912345678", "email": "TEST@example.test"},
        creating=True,
    )
    assert values["full_name"] == "Test" and values["email"] == "test@example.test"
    assert "phone_verified_at" not in values
    assert customer_fields({"email": None, "last_name": None}, creating=False) == {
        "email": None,
        "last_name": None,
    }
    with pytest.raises(ValidationError):
        CreateAdministrativeCustomer(
            full_name="Test", phone="+51912345678", user_id=uuid4()
        )
