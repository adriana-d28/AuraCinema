"""Database engine and per-request session management.

The application uses synchronous SQLAlchemy. FastAPI runs synchronous route
handlers in a worker thread pool, so blocking database calls do not block the
event loop, and the code stays simpler to read and test than an async stack.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# Seconds to wait for a new database connection. Without a limit, an
# unreachable host can make requests (and the readiness check) hang forever.
CONNECT_TIMEOUT_SECONDS = 10


def create_db_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        # Checks connections before use so a restarted PostgreSQL container
        # does not cause errors from stale pooled connections.
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


@lru_cache
def get_engine() -> Engine:
    """Create the engine lazily so importing the app does not open connections."""
    return create_db_engine(get_settings().database_url.get_secret_value())


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    # expire_on_commit=False keeps loaded attributes usable after commit, so
    # route handlers can serialise returned objects without extra queries.
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding one session per request.

    The session is always closed, and any uncommitted transaction is rolled
    back, even if the request handler raises an exception.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
