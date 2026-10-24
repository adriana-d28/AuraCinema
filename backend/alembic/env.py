"""Alembic migration environment.

The target database is resolved in this order:
1. A URL passed programmatically via `config.attributes["database_url"]`
   (used by the test suite to migrate the isolated test database);
2. the application's DATABASE_URL setting.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Importing the models registers their tables on Base.metadata, which
# autogenerate compares against the live database.
import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import CONNECT_TIMEOUT_SECONDS

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_database_url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return url
    return get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Generate SQL scripts without connecting (alembic upgrade head --sql)."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes too, not only added/removed columns.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
