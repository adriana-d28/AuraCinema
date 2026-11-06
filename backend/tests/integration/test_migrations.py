"""Integration tests for database connectivity and the Alembic migration."""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from app.core.titles import build_search_title
from tests.conftest import alembic_config
from tests.helpers import TEST_MOVIES

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
        # Since the movie catalogue migration each table has two foreign keys.
        foreign_keys = {fk["name"]: fk for fk in inspector.get_foreign_keys(table)}
        assert set(foreign_keys) == {f"fk_{table}_user_id_users", f"fk_{table}_movie_id_movies"}

        to_users = foreign_keys[f"fk_{table}_user_id_users"]
        assert to_users["referred_table"] == "users"
        assert to_users["options"].get("ondelete") == "CASCADE"

        # No ON DELETE action: a movie that is still referenced cannot be deleted.
        to_movies = foreign_keys[f"fk_{table}_movie_id_movies"]
        assert to_movies["referred_table"] == "movies"
        assert to_movies["constrained_columns"] == ["movie_id"]
        assert to_movies["referred_columns"] == ["movie_id"]
        assert to_movies["options"].get("ondelete") is None


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
    assert {"users", "ratings", "watchlist_items", "movies", "movie_metadata"} <= set(
        inspect(migrated_engine).get_table_names()
    )


# --- Movie catalogue migrations (413ce2f03dd0 and 6bfe976fc037) -------------

MOVIES_REVISION = "413ce2f03dd0"


def test_movies_table_columns_and_primary_key(migrated_engine: Engine):
    inspector = inspect(migrated_engine)
    columns = {c["name"]: c for c in inspector.get_columns("movies")}
    # search_title was added by revision 4b9b12262d50 (normalized search).
    assert list(columns) == ["movie_id", "title", "genres", "tmdb_id", "imdb_id", "search_title"]

    primary_key = inspector.get_pk_constraint("movies")
    assert primary_key["name"] == "pk_movies"
    assert primary_key["constrained_columns"] == ["movie_id"]
    # movie_id comes from MovieLens, so it must not have a sequence/default.
    assert columns["movie_id"]["default"] is None
    assert columns["movie_id"].get("autoincrement") is not True

    assert {name: c["nullable"] for name, c in columns.items()} == {
        "movie_id": False,
        "title": False,
        "genres": False,
        "tmdb_id": True,
        "imdb_id": True,
        "search_title": False,
    }
    assert {c["name"] for c in inspector.get_check_constraints("movies")} == {
        "ck_movies_movie_id_positive",
        "ck_movies_tmdb_id_positive",
        "ck_movies_imdb_id_positive",
    }


def test_models_match_migrations(migrated_engine: Engine):
    """Alembic finds no difference between the ORM models and the migrated schema."""
    command.check(alembic_config())  # Raises if autogenerate would create a migration.


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


def test_movie_metadata_table_columns_and_nullability(migrated_engine: Engine):
    columns = {c["name"]: c for c in inspect(migrated_engine).get_columns("movie_metadata")}
    assert {name: c["nullable"] for name, c in columns.items()} == {
        "movie_id": False,
        "overview": True,
        "release_date": True,
        "runtime": True,
        "poster_path": True,
        "metadata_source": True,
        "metadata_updated_at": True,
        "refresh_status": True,
        "refresh_attempted_at": True,
        "tmdb_validation_status": False,
        "tmdb_validated_at": True,
        "tmdb_validation_note": True,
        "tmdb_validation_http_status": True,
    }
    assert columns["metadata_updated_at"]["type"].timezone is True
    assert "not_checked" in columns["tmdb_validation_status"]["default"]
    # movie_id comes from movies, so it has no sequence of its own.
    assert columns["movie_id"]["default"] is None


def test_movie_metadata_primary_key_is_also_the_foreign_key(migrated_engine: Engine):
    inspector = inspect(migrated_engine)
    primary_key = inspector.get_pk_constraint("movie_metadata")
    assert (primary_key["name"], primary_key["constrained_columns"]) == (
        "pk_movie_metadata",
        ["movie_id"],
    )
    (foreign_key,) = inspector.get_foreign_keys("movie_metadata")
    assert foreign_key["name"] == "fk_movie_metadata_movie_id_movies"
    assert foreign_key["constrained_columns"] == ["movie_id"]
    assert (foreign_key["referred_table"], foreign_key["referred_columns"]) == (
        "movies",
        ["movie_id"],
    )
    assert foreign_key["options"].get("ondelete") == "CASCADE"
    assert {c["name"] for c in inspector.get_check_constraints("movie_metadata")} == {
        "ck_movie_metadata_runtime_positive",
        "ck_movie_metadata_refresh_status_valid",
        "ck_movie_metadata_tmdb_validation_status_valid",
    }


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
