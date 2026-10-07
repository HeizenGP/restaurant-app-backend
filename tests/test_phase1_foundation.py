import pytest
from pydantic import ValidationError
from sqlmodel import SQLModel

from app.modules.auth.infrastructure.persistence import models as auth_models
from app.modules.branches.infrastructure.persistence import models as branch_models
from app.modules.customers.infrastructure.persistence import models as customer_models
from app.shared.infrastructure.config.settings import Settings

EXPECTED_PHASE_ONE_TABLES = {
    "roles",
    "permissions",
    "role_permissions",
    "users",
    "user_roles",
    "refresh_tokens",
    "branches",
    "branch_hours",
    "staff_assignments",
    "customers",
    "otp_challenges",
    "customer_addresses",
}


def test_phase_one_metadata_tables_remain_available() -> None:
    assert auth_models and branch_models and customer_models
    assert EXPECTED_PHASE_ONE_TABLES <= set(SQLModel.metadata.tables)


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {
            "jwt_secret": "a" * 48,
            "otp_pepper": "b" * 48,
            "otp_debug_expose_code": True,
        },
        {"jwt_secret": "short", "otp_pepper": "b" * 48},
        {"jwt_secret": "a" * 48, "otp_pepper": "short"},
    ],
)
def test_production_rejects_insecure_auth_settings(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", **updates)


def test_production_accepts_strong_auth_settings_without_debug() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="a" * 48,
        otp_pepper="b" * 48,
        otp_debug_expose_code=False,
    )

    assert settings.app_env == "production"
    assert "a" * 48 not in repr(settings)
    assert "b" * 48 not in repr(settings)
