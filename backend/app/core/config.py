"""Application settings loaded from environment variables.

Settings are validated once at startup by Pydantic. If a required value is
missing or invalid, the application refuses to start and reports which
setting is wrong, without echoing secret values back to the console.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Placeholder used in .env.example. Rejecting it prevents the example file
# from being copied into a real environment without generating a secret.
EXAMPLE_SECRET_PLACEHOLDER = "change-me-generate-a-random-secret-of-at-least-32-characters"

# HMAC-SHA256 keys should be at least as long as the hash output (32 bytes).
MIN_SECRET_LENGTH = 32


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed configuration for the backend.

    Values come from real environment variables first, then from a local
    `.env` file (which must never be committed).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Without this, a validation error would print the rejected value,
        # e.g. a (too short) JWT secret or a database URL with its password.
        hide_input_in_errors=True,
    )

    app_env: Environment = Environment.DEVELOPMENT

    # SecretStr keeps the URL (which contains the DB password) out of reprs and logs.
    database_url: SecretStr

    jwt_secret_key: SecretStr
    # Only symmetric HMAC algorithms are accepted; the same key signs and verifies.
    jwt_algorithm: str = Field(default="HS256", pattern=r"^HS(256|384|512)$")
    access_token_expire_minutes: int = Field(default=60, ge=1, le=24 * 60)

    # NoDecode lets us accept a simple comma-separated string instead of JSON.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # TMDB (The Movie Database) supplies optional extra movie information such
    # as the overview and poster. The value is the "API Read Access Token" from
    # the TMDB account settings, sent as a Bearer header. It is used only by the
    # maintenance scripts that fill the movie_metadata table; the API itself
    # reads that table and works without a token.
    tmdb_api_read_access_token: SecretStr | None = None
    # Maximum seconds to wait for one TMDB request, so a slow external service
    # cannot block a script indefinitely.
    tmdb_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # Stored metadata older than this is refreshed by
    # scripts/refresh_movie_metadata.py (default: 30 days).
    tmdb_metadata_refresh_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        # PostgreSQL is the required database for this project; the psycopg 3
        # driver must be selected explicitly in the SQLAlchemy URL.
        url = value.get_secret_value()
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("must be a PostgreSQL URL starting with 'postgresql+psycopg://'")
        PostgresDsn(url)  # Raises if the URL is malformed.
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret == EXAMPLE_SECRET_PLACEHOLDER:
            raise ValueError("is still the placeholder from .env.example; generate a real secret")
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters long")
        return value

    @field_validator("tmdb_api_read_access_token", mode="before")
    @classmethod
    def empty_tmdb_token_means_not_configured(cls, value: object) -> object:
        # .env.example contains "TMDB_API_READ_ACCESS_TOKEN=" (empty); treat an
        # empty or blank value the same as a missing one.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        # A wildcard origin would allow any website to call the API from a
        # user's browser, so explicit origins are required.
        if "*" in value:
            raise ValueError("wildcard '*' is not allowed; list explicit origins")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton (cached so the environment is parsed once)."""
    return Settings()
