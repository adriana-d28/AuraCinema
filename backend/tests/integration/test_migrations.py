"""Integration tests for the Alembic migrations."""

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from app.core.titles import build_search_title
from tests.conftest import alembic_config
from tests.helpers import TEST_MOVIES

pytestmark = pytest.mark.db


def test_migration_downgrade_and_upgrade_round_trip(migrated_engine: Engine):
    """The migration can be fully rolled back and reapplied on a clean database."""
    config = alembic_config()
    command.downgrade(config, "base")
    tables_after_downgrade = set(inspect(migrated_engine).get_table_names())
    assert tables_after_downgrade.isdisjoint({"users", "ratings", "watchlist_items"})

    command.upgrade(config, "head")
    assert {"users", "ratings", "watchlist_items", "movies", "movie_metadata"} <= set(
        inspect(migrated_engine).get_table_names()
    )


def test_models_match_migrations(migrated_engine: Engine):
    """Alembic finds no difference between the ORM models and the migrated schema.

    Together with tests/integration/test_models.py, which triggers every named
    constraint, this replaces column-by-column inspection of the schema."""
    command.check(alembic_config())  # Raises if autogenerate would create a migration.


# --- Movie catalogue migrations (413ce2f03dd0 and 6bfe976fc037) -------------

MOVIES_REVISION = "413ce2f03dd0"


def test_foreign_key_migration_refuses_unknown_movies_and_keeps_data(clean_db: Engine):
    """With a rating for a movie that is not in the catalogue, the FK migration
    stops with a clear error instead of deleting user data; after the movie is
    added to the catalogue the migration succeeds and the rating is kept."""
    config = alembic_config()
    command.downgrade(config, MOVIES_REVISION)  # Removes only the movie foreign keys.
    try:
        with clean_db.begin() as connection:
            user_id = connection.execute(
                text(
                    "INSERT INTO users (email, password_hash) VALUES ('m@example.com', 'x') "
                    "RETURNING id"
                )
            ).scalar_one()
            connection.execute(
                text(
                    "INSERT INTO ratings (user_id, movie_id, rating) VALUES (:u, 1, 4.0), "
                    "(:u, 999999, 3.0)"
                ),
                {"u": user_id},
            )

        with pytest.raises(RuntimeError, match="Cannot add the movie foreign keys"):
            command.upgrade(config, "head")

        with clean_db.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 2
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == MOVIES_REVISION
            )

        # Fix the data the way an operator would: add the missing catalogue movie.
        with clean_db.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO movies (movie_id, title, genres) "
                    "VALUES (999999, 'Placeholder for test', 'Drama')"
                )
            )
        command.upgrade(config, "head")

        with clean_db.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 2
    finally:
        # Leave the schema at head for the other tests, even if this test failed.
        with clean_db.begin() as connection:
            connection.execute(text("TRUNCATE users, ratings, watchlist_items CASCADE"))
        command.upgrade(config, "head")


# --- Metadata refinements (bbf98bce938e and 4b9b12262d50) -----------------------

FK_REVISION = "6bfe976fc037"  # Last revision before the metadata refinements.


def test_metadata_migrations_downgrade_and_upgrade_preserve_existing_data(clean_db: Engine):
    """Downgrading removes only the new table and column; upgrading again
    recreates them and fills search_title for the existing movies, while
    movies, ratings and watchlist entries stay untouched."""
    config = alembic_config()
    with clean_db.begin() as connection:
        user_id = connection.execute(
            text("INSERT INTO users (email, password_hash) VALUES ('d@x.io', 'x') RETURNING id")
        ).scalar_one()
        connection.execute(
            text("INSERT INTO ratings (user_id, movie_id, rating) VALUES (:u, 2571, 4.5)"),
            {"u": user_id},
        )
        connection.execute(
            text("INSERT INTO watchlist_items (user_id, movie_id) VALUES (:u, 293)"), {"u": user_id}
        )
        connection.execute(text("INSERT INTO movie_metadata (movie_id, runtime) VALUES (1, 81)"))

    try:
        command.downgrade(config, FK_REVISION)
        inspector = inspect(clean_db)
        assert "movie_metadata" not in inspector.get_table_names()
        assert "search_title" not in {c["name"] for c in inspector.get_columns("movies")}

        command.upgrade(config, "head")
        with clean_db.connect() as connection:
            stored = dict(
                connection.execute(text("SELECT movie_id, search_title FROM movies")).all()
            )
            assert stored == {m[0]: build_search_title(m[1]) for m in TEST_MOVIES}  # Backfilled.
            assert connection.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT count(*) FROM watchlist_items")).scalar_one() == 1
            )
            assert connection.execute(text("SELECT count(*) FROM movies")).scalar_one() == len(
                TEST_MOVIES
            )
            # Derived TMDB data is dropped by the downgrade; the scripts can fetch it again.
            assert connection.execute(text("SELECT count(*) FROM movie_metadata")).scalar_one() == 0
            # The temporary empty default used for the backfill was removed.
            column = {c["name"]: c for c in inspect(clean_db).get_columns("movies")}["search_title"]
            assert column["default"] is None
    finally:
        command.upgrade(config, "head")


def test_search_title_migration_produces_sql_offline():
    """Offline mode (--sql) works: no database query is needed by the backfill step."""
    import io

    buffer = io.StringIO()
    config = alembic_config()
    config.output_buffer = buffer
    command.upgrade(config, f"{FK_REVISION}:head", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE movie_metadata" in sql
    assert "ALTER TABLE movies ADD COLUMN search_title TEXT" in sql
