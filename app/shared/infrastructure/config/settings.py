from functools import lru_cache
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
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

    jwt_secret: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = Field(default="restaurant-app-backend", min_length=1)
    jwt_audience: str = Field(default="restaurant-app", min_length=1)
    access_token_expire_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=365)
    phone_verification_token_expire_minutes: int = Field(default=10, ge=1, le=120)

    otp_pepper: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
    )
    otp_expire_minutes: int = Field(default=5, ge=1, le=60)
    otp_max_attempts: int = Field(default=5, ge=1, le=20)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=0, le=3600)
    otp_debug_expose_code: bool = False

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

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.otp_debug_expose_code and self.app_env not in {"development", "test"}:
            raise ValueError("OTP debugging is only allowed in development/test")
        if self.app_env in {"development", "test"}:
            # Ephemeral defaults keep health/tests usable without shared credentials.
            # Configure stable secrets in .env to retain sessions across restarts.
            if not self.jwt_secret.get_secret_value():
                self.jwt_secret = SecretStr(token_urlsafe(48))
            if not self.otp_pepper.get_secret_value():
                self.otp_pepper = SecretStr(token_urlsafe(48))
            return self
        secrets = {
            "JWT_SECRET": self.jwt_secret.get_secret_value(),
            "OTP_PEPPER": self.otp_pepper.get_secret_value(),
        }
        for name, value in secrets.items():
            if (
                len(value) < 32
                or "change_me" in value.lower()
                or "change-before" in value
            ):
                raise ValueError(
                    f"{name} must be a strong non-placeholder secret "
                    "in staging/production"
                )
        if self.otp_debug_expose_code:
            raise ValueError("OTP_DEBUG_EXPOSE_CODE cannot be enabled in production")
        return self

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
