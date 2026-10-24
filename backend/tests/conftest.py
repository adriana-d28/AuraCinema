"""Shared test fixtures.

Safety rules for the test database:
- Tests never use DATABASE_URL from .env. They use TEST_DATABASE_URL instead,
  and refuse to run unless the database name ends with "_test".
- The test database schema is dropped and rebuilt with Alembic at the start of
  each test session, and tables are truncated before every database test.

The environment is configured at import time, before the application is
imported, because settings are read and cached on first use.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from tests.helpers import TEST_JWT_SECRET, auth_headers

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _resolve_test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(BACKEND_DIR / ".env").get(
        "TEST_DATABASE_URL"
    )
    if not url:
        pytest.exit("TEST_DATABASE_URL is not set (see .env.example)", returncode=2)
    database_name = make_url(url).database or ""
    if not database_name.endswith("_test"):
        # Guard against accidentally wiping the development database.
        pytest.exit(
            f"Refusing to run: test database name '{database_name}' must end with '_test'",
            returncode=2,
        )
    return url


TEST_DATABASE_URL = _resolve_test_database_url()

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET_KEY"] = TEST_JWT_SECRET
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

# Imported only after the environment is configured.
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.db.session import get_engine, get_session_factory  # noqa: E402

TRUNCATE_SQL = text("TRUNCATE users, ratings, watchlist_items RESTART IDENTITY CASCADE")


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    # Keep pytest's logging configuration instead of alembic.ini's.
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """Rebuild the test database from scratch using the Alembic migrations.

    This exercises the real migration on a clean database at the start of
    every test run, instead of using Base.metadata.create_all().
    """
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def clean_db(migrated_engine: Engine) -> Engine:
    """Empty all application tables so each test starts from a known state."""
    with migrated_engine.begin() as connection:
        connection.execute(TRUNCATE_SQL)
    return migrated_engine


@pytest.fixture
def db_session(clean_db: Engine) -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(clean_db: Engine):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def alice_headers(client) -> dict[str, str]:
    return auth_headers(client, "alice@example.com")


@pytest.fixture
def bob_headers(client) -> dict[str, str]:
    return auth_headers(client, "bob@example.com")
