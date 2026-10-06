from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="Restaurant App Backend", min_length=1)
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_debug: bool = False
    app_version: str = Field(default="0.1.0", min_length=1)
    api_v1_prefix: str = "/api/v1"

    database_url: SecretStr | None = Field(default=None, repr=False)
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "restaurant_db"
    db_user: str = "postgres"
    db_password: SecretStr = Field(default=SecretStr(""), repr=False)
    database_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if (
            not value.startswith("/")
            or value.endswith("/")
            or any(character in value for character in "?# ")
        ):
            raise ValueError("API_V1_PREFIX must be a path without a trailing slash")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
        if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            raise ValueError("DATABASE_URL must use PostgreSQL with asyncpg")
        if not url.host or not url.database:
            raise ValueError("DATABASE_URL must specify a host and database")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        origins = []
        for value in values:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
                or any(character.isspace() for character in value)
            ):
                raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins")
            # Accessing port also validates its range and syntax.
            _ = url.port
            origins.append(value.rstrip("/"))
        return origins

    @property
    def database_connection_url(self) -> URL:
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value()).set(
                drivername="postgresql+asyncpg"
            )
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
