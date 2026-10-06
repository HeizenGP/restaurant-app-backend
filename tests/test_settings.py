import pytest
from pydantic import ValidationError

from app.shared.infrastructure.config.settings import Settings


def test_environment_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "Environment backend")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000, https://example.com/")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Environment backend"
    assert settings.cors_origins == ["http://localhost:3000", "https://example.com"]


def test_database_url_handles_special_password_characters(settings: Settings) -> None:
    configured = settings.model_copy(
        update={"db_password": settings.db_password.__class__("p@ss:/%word")}
    )
    url = configured.database_connection_url

    assert url.drivername == "postgresql+asyncpg"
    assert url.password == "p@ss:/%word"
    assert "p@ss" not in str(url)
    assert "p@ss" not in repr(configured)


def test_database_url_overrides_individual_fields() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:secret-password@localhost:5432/override_db",
        db_name="ignored_db",
    )

    assert settings.database_connection_url.drivername == "postgresql+asyncpg"
    assert settings.database_connection_url.database == "override_db"
    assert "secret-password" not in repr(settings)


@pytest.mark.parametrize("origin", ["*", "ftp://example.com", "http://localhost/path"])
def test_invalid_cors_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_non_postgresql_database_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///test.db")
