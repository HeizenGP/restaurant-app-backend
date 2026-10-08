import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.shared.infrastructure.config.settings import Settings
from scripts.postgres_backup import connection_environment, validate_restore_target
from tests.integration.test_phase1_postgresql import guarded_test_url

STRONG = "phase12-test-only-strong-secret-123456789XYZ"


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize(
    "secret",
    ["", "short", "a" * 64, "change_me_" * 8, "placeholder-" * 8, "replace-me-" * 8],
)
def test_release_secrets_fail_closed(environment, secret):
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None,
            app_env=environment,
            jwt_secret=secret,
            otp_pepper=STRONG,
            database_url=None,
            db_password=STRONG,
            app_debug=False,
        )
    assert secret not in str(exc.value) if secret else True


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_debug_and_otp_debug_rejected(environment):
    for field in ("app_debug", "otp_debug_expose_code"):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                app_env=environment,
                jwt_secret=STRONG,
                otp_pepper=STRONG,
                db_password=STRONG,
                **{field: True},
            )


def test_production_example_deliberately_cannot_start(monkeypatch):
    from scripts.export_openapi import ROOT

    # CI's APP_ENV=test/strong TEST secrets must not mask the template values.
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=ROOT / ".env.production.example")


@pytest.mark.parametrize("environment", ["staging", "production"])
@pytest.mark.parametrize("password", ["", "change_me", "placeholder", "replace-me"])
@pytest.mark.parametrize("use_url", [False, True])
def test_deployment_db_credentials_fail_closed(environment, password, use_url):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env=environment,
            app_debug=False,
            jwt_secret=STRONG,
            otp_pepper=STRONG,
            database_url=(
                "postgresql://test:" + password + "@localhost/restaurant_test"
                if use_url
                else None
            ),
            db_password=password,
        )


@pytest.mark.parametrize(
    "database",
    ["restaurant_db", "restaurant_prod_test", "production_test", "staging_test", ""],
)
def test_pg_guard_rejects_normal_production_or_unnamed(monkeypatch, database):
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql://test:TEST@127.0.0.1/" + database
    )
    request = SimpleNamespace(config=SimpleNamespace(getoption=lambda _: "integration"))
    with pytest.raises(pytest.fail.Exception):
        guarded_test_url(request)


def test_ci_missing_test_database_fails_not_skips(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("REQUIRE_POSTGRES_INTEGRATION", "1")
    request = SimpleNamespace(config=SimpleNamespace(getoption=lambda _: "integration"))
    with pytest.raises(pytest.fail.Exception):
        guarded_test_url(request)


@pytest.mark.parametrize(
    "database", ["restaurant_db", "prod_restore", "restaurant_test"]
)
def test_restore_guard_rejects_normal_or_production(database):
    url = make_url("postgresql://test:TEST@localhost/" + database)
    normal = make_url("postgresql://test:TEST@127.0.0.1/restaurant_test")
    with pytest.raises(ValueError):
        validate_restore_target(url, normal)


def test_backup_credentials_not_in_subprocess_arguments(monkeypatch):
    monkeypatch.setenv(
        "BACKUP_DATABASE_URL",
        "postgresql://test:TEST_SENTINEL@localhost/restaurant_test",
    )
    monkeypatch.setenv("PGHOSTADDR", "unsafe-inherited-host")
    _, env = connection_environment("BACKUP_DATABASE_URL")
    assert env["PGPASSWORD"] == "TEST_SENTINEL"
    assert env["PGDATABASE"] == "restaurant_test" and "PGHOSTADDR" not in env
    assert os.environ["PGHOSTADDR"] == "unsafe-inherited-host"
