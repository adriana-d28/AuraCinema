"""Unit tests for settings validation (no database required)."""

import pytest
from pydantic import ValidationError

from app.core.config import EXAMPLE_SECRET_PLACEHOLDER, Environment, Settings

VALID_URL = "postgresql+psycopg://user:pw@127.0.0.1:5432/some_db"
VALID_SECRET = "x" * 40


def make_settings(**overrides) -> Settings:
    # _env_file=None ignores the developer's .env so each test controls its input.
    values = {"database_url": VALID_URL, "jwt_secret_key": VALID_SECRET} | overrides
    return Settings(_env_file=None, **values)


def test_valid_settings_are_accepted_with_defaults():
    settings = make_settings()
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 60
    assert settings.cors_origins == ["http://localhost:5173"]


@pytest.mark.parametrize("missing", ["DATABASE_URL", "JWT_SECRET_KEY"])
def test_missing_required_setting_is_rejected(monkeypatch, missing):
    monkeypatch.setenv("DATABASE_URL", VALID_URL)
    monkeypatch.setenv("JWT_SECRET_KEY", VALID_SECRET)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)
    assert missing.lower() in str(exc_info.value)


def test_short_jwt_secret_is_rejected():
    with pytest.raises(ValidationError, match="at least 32 characters"):
        make_settings(jwt_secret_key="too-short")


def test_example_placeholder_secret_is_rejected():
    with pytest.raises(ValidationError, match="placeholder"):
        make_settings(jwt_secret_key=EXAMPLE_SECRET_PLACEHOLDER)


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///./local.db",  # PostgreSQL is mandatory
        "postgresql://user:pw@127.0.0.1/db",  # driver must be psycopg 3
        "not-a-url",
    ],
)
def test_non_postgresql_database_url_is_rejected(url):
    with pytest.raises(ValidationError):
        make_settings(database_url=url)


def test_unsupported_jwt_algorithm_is_rejected():
    with pytest.raises(ValidationError):
        make_settings(jwt_algorithm="none")


@pytest.mark.parametrize("minutes", [0, -5, 24 * 60 + 1])
def test_out_of_range_token_lifetime_is_rejected(minutes):
    with pytest.raises(ValidationError):
        make_settings(access_token_expire_minutes=minutes)


def test_cors_origins_are_parsed_from_comma_separated_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://auracinema.example ")
    settings = make_settings()
    assert settings.cors_origins == ["http://localhost:5173", "https://auracinema.example"]


def test_wildcard_cors_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValidationError, match="wildcard"):
        make_settings()


def test_invalid_environment_is_rejected():
    with pytest.raises(ValidationError):
        make_settings(app_env="staging")
    assert make_settings(app_env="production").app_env is Environment.PRODUCTION


def test_secrets_are_masked_in_representation():
    settings = make_settings()
    text = repr(settings) + str(settings.model_dump())
    assert VALID_SECRET not in text
    assert "pw@" not in text


def test_validation_error_does_not_echo_secret_value():
    with pytest.raises(ValidationError) as exc_info:
        make_settings(jwt_secret_key="short-secret-value")
    assert "short-secret-value" not in str(exc_info.value)
