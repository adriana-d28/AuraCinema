"""Integration tests for database connectivity and the Alembic migration."""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config

pytestmark = pytest.mark.db


def test_database_is_reachable(migrated_engine: Engine):
    with migrated_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1


def test_database_is_postgresql(migrated_engine: Engine):
    assert migrated_engine.dialect.name == "postgresql"


def test_database_is_at_latest_migration(migrated_engine: Engine):
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with migrated_engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert current == head


def test_migration_creates_expected_tables_and_constraints(migrated_engine: Engine):
    inspector = inspect(migrated_engine)
    assert {"users", "ratings", "watchlist_items"} <= set(inspector.get_table_names())

    assert {c["name"] for c in inspector.get_unique_constraints("users")} == {"uq_users_email"}
    assert {c["name"] for c in inspector.get_unique_constraints("ratings")} == {
        "uq_ratings_user_id_movie_id"
    }
    assert {c["name"] for c in inspector.get_unique_constraints("watchlist_items")} == {
        "uq_watchlist_items_user_id_movie_id"
    }
    assert {c["name"] for c in inspector.get_check_constraints("ratings")} == {
        "ck_ratings_movie_id_positive",
        "ck_ratings_rating_half_star_range",
    }
    for table in ("ratings", "watchlist_items"):
        (foreign_key,) = inspector.get_foreign_keys(table)
        assert foreign_key["referred_table"] == "users"
        assert foreign_key["options"].get("ondelete") == "CASCADE"


def test_timestamps_are_timezone_aware_columns(migrated_engine: Engine):
    inspector = inspect(migrated_engine)
    columns = {c["name"]: c for c in inspector.get_columns("ratings")}
    assert columns["rated_at"]["type"].timezone is True
    assert columns["created_at"]["type"].timezone is True


def test_migration_downgrade_and_upgrade_round_trip(migrated_engine: Engine):
    """The migration can be fully rolled back and reapplied on a clean database."""
    config = alembic_config()
    command.downgrade(config, "base")
    tables_after_downgrade = set(inspect(migrated_engine).get_table_names())
    assert tables_after_downgrade.isdisjoint({"users", "ratings", "watchlist_items"})

    command.upgrade(config, "head")
    assert {"users", "ratings", "watchlist_items"} <= set(
        inspect(migrated_engine).get_table_names()
    )
