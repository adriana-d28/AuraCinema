"""Integration tests for ORM models and database constraints on PostgreSQL.

These tests insert data directly through the ORM (bypassing the API) to prove
that the database itself enforces the integrity rules.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Movie, MovieMetadata, Rating, User, WatchlistItem
from app.models.movie_metadata import RefreshStatus, TmdbIdValidationStatus
from tests.helpers import TEST_MOVIES, UNKNOWN_MOVIE_ID

pytestmark = pytest.mark.db


def create_user(db: Session, email: str = "user@example.com") -> User:
    user = User(email=email, password_hash=hash_password("irrelevant-password"))
    db.add(user)
    db.commit()
    return user


def test_user_is_persisted_with_utc_timestamp(db_session: Session):
    user = create_user(db_session)
    db_session.expire_all()
    stored = db_session.get(User, user.id)
    assert stored.email == "user@example.com"
    assert stored.created_at.utcoffset().total_seconds() == 0


def test_duplicate_email_is_rejected(db_session: Session):
    create_user(db_session, "same@example.com")
    with pytest.raises(IntegrityError, match="uq_users_email"):
        create_user(db_session, "same@example.com")


def test_non_lowercase_email_is_rejected_by_database(db_session: Session):
    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        create_user(db_session, "Mixed@Example.com")


def test_rating_is_persisted(db_session: Session):
    user = create_user(db_session)
    db_session.add(Rating(user_id=user.id, movie_id=318, rating=4.5))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.scalar(select(Rating).where(Rating.user_id == user.id))
    assert (stored.movie_id, stored.rating) == (318, 4.5)
    assert stored.rated_at.utcoffset().total_seconds() == 0


def test_duplicate_rating_for_same_user_and_movie_is_rejected(db_session: Session):
    user = create_user(db_session)
    db_session.add(Rating(user_id=user.id, movie_id=1, rating=3.0))
    db_session.commit()
    db_session.add(Rating(user_id=user.id, movie_id=1, rating=4.0))
    with pytest.raises(IntegrityError, match="uq_ratings_user_id_movie_id"):
        db_session.commit()


@pytest.mark.parametrize("value", [0.0, 0.3, 5.5, 6.0, -1.0])
def test_invalid_rating_value_is_rejected_by_database(db_session: Session, value):
    user = create_user(db_session)
    db_session.add(Rating(user_id=user.id, movie_id=1, rating=value))
    with pytest.raises(IntegrityError, match="ck_ratings_rating_half_star_range"):
        db_session.commit()


@pytest.mark.parametrize("model", [Rating, WatchlistItem])
def test_non_positive_movie_id_is_rejected_by_database(db_session: Session, model):
    user = create_user(db_session)
    extra = {"rating": 3.0} if model is Rating else {}
    db_session.add(model(user_id=user.id, movie_id=0, **extra))
    with pytest.raises(IntegrityError, match="movie_id_positive"):
        db_session.commit()


@pytest.mark.parametrize("model", [Rating, WatchlistItem])
def test_foreign_key_to_missing_user_is_rejected(db_session: Session, model):
    extra = {"rating": 3.0} if model is Rating else {}
    db_session.add(model(user_id=999_999, movie_id=1, **extra))
    with pytest.raises(IntegrityError, match="fk_"):
        db_session.commit()


def test_watchlist_item_is_persisted(db_session: Session):
    user = create_user(db_session)
    db_session.add(WatchlistItem(user_id=user.id, movie_id=2571))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user.id))
    assert stored.movie_id == 2571
    assert stored.added_at.utcoffset().total_seconds() == 0


def test_duplicate_watchlist_entry_is_rejected(db_session: Session):
    user = create_user(db_session)
    db_session.add(WatchlistItem(user_id=user.id, movie_id=1))
    db_session.commit()
    db_session.add(WatchlistItem(user_id=user.id, movie_id=1))
    with pytest.raises(IntegrityError, match="uq_watchlist_items_user_id_movie_id"):
        db_session.commit()


def test_deleting_a_user_cascades_to_ratings_and_watchlist(db_session: Session):
    user = create_user(db_session)
    other = create_user(db_session, "other@example.com")
    db_session.add_all(
        [
            Rating(user_id=user.id, movie_id=1, rating=4.0),
            WatchlistItem(user_id=user.id, movie_id=2),
            Rating(user_id=other.id, movie_id=1, rating=2.0),
        ]
    )
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Rating)) == 1
    assert db_session.scalar(select(func.count()).select_from(WatchlistItem)) == 0
    assert db_session.get(User, other.id) is not None


# --- Movie catalogue -------------------------------------------------------


def test_movie_is_persisted_with_original_movielens_id(db_session: Session):
    # A large real MovieLens ID is stored as-is (no sequence renumbers it).
    db_session.add(
        Movie(movie_id=288513, title="Test Movie (2023)", genres="Drama", tmdb_id=1, imdb_id=2)
    )
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(Movie, 288513)
    assert (stored.movie_id, stored.title, stored.genres) == (288513, "Test Movie (2023)", "Drama")


def test_duplicate_movie_id_is_rejected(db_session: Session):
    db_session.add(Movie(movie_id=1, title="Another title", genres="Drama"))
    with pytest.raises(IntegrityError, match="pk_movies"):
        db_session.commit()


@pytest.mark.parametrize(
    ("field", "constraint"),
    [
        ("movie_id", "movie_id_positive"),
        ("tmdb_id", "tmdb_id_positive"),
        ("imdb_id", "imdb_id_positive"),
    ],
)
def test_non_positive_movie_identifiers_are_rejected(db_session: Session, field, constraint):
    values = {"movie_id": 500_000, "title": "X", "genres": "Drama", field: 0}
    db_session.add(Movie(**values))
    with pytest.raises(IntegrityError, match=constraint):
        db_session.commit()


@pytest.mark.parametrize("column", ["title", "genres"])
def test_movie_title_and_genres_are_required(db_session: Session, column):
    values = {"movie_id": 500_000, "title": "X", "genres": "Drama", column: None}
    db_session.add(Movie(**values))
    with pytest.raises(IntegrityError, match="not-null"):
        db_session.commit()


@pytest.mark.parametrize("model", [Rating, WatchlistItem])
def test_foreign_key_to_unknown_movie_is_rejected(db_session: Session, model):
    user = create_user(db_session)
    extra = {"rating": 3.0} if model is Rating else {}
    db_session.add(model(user_id=user.id, movie_id=UNKNOWN_MOVIE_ID, **extra))
    with pytest.raises(IntegrityError, match=f"fk_{model.__tablename__}_movie_id_movies"):
        db_session.commit()


@pytest.mark.parametrize("model", [Rating, WatchlistItem])
def test_movie_with_user_data_cannot_be_deleted(db_session: Session, model):
    """Deleting a catalogue movie must never silently remove users' data."""
    user = create_user(db_session)
    extra = {"rating": 3.0} if model is Rating else {}
    db_session.add(model(user_id=user.id, movie_id=318, **extra))
    db_session.commit()

    db_session.delete(db_session.get(Movie, 318))
    with pytest.raises(IntegrityError, match="fk_"):
        db_session.commit()
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(model)) == 1


# --- Movie metadata (one-to-one with movies) -----------------------------------


def test_metadata_is_persisted_and_linked_both_ways(db_session: Session):
    db_session.add(
        MovieMetadata(
            movie_id=1,
            overview="Toys come alive.",
            release_date=date(1995, 10, 30),
            runtime=81,
            poster_path="/poster.jpg",
            metadata_source="tmdb",
            metadata_updated_at=datetime(2026, 11, 1, tzinfo=UTC),
        )
    )
    db_session.commit()
    db_session.expire_all()

    movie = db_session.get(Movie, 1)
    assert movie.movie_metadata.runtime == 81
    assert movie.movie_metadata.movie is movie
    assert movie.movie_metadata.has_metadata is True
    assert movie.movie_metadata.metadata_updated_at.utcoffset().total_seconds() == 0


def test_metadata_fields_are_nullable_and_validation_defaults_to_not_checked(db_session):
    db_session.add(MovieMetadata(movie_id=2))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(MovieMetadata, 2)
    assert (stored.overview, stored.release_date, stored.runtime, stored.poster_path) == (
        None,
        None,
        None,
        None,
    )
    assert stored.has_metadata is False
    assert stored.tmdb_validation_status == "not_checked"


def test_validation_status_server_default_applies_to_raw_inserts(db_session: Session):
    db_session.execute(text("INSERT INTO movie_metadata (movie_id) VALUES (3)"))
    db_session.commit()
    assert db_session.get(MovieMetadata, 3).tmdb_validation_status == "not_checked"


def test_only_one_metadata_row_per_movie(db_session: Session):
    db_session.add(MovieMetadata(movie_id=1))
    db_session.commit()
    db_session.expunge_all()
    db_session.add(MovieMetadata(movie_id=1))
    with pytest.raises(IntegrityError, match="pk_movie_metadata"):
        db_session.commit()


def test_metadata_for_a_movie_outside_the_catalogue_is_rejected(db_session: Session):
    db_session.add(MovieMetadata(movie_id=UNKNOWN_MOVIE_ID))
    with pytest.raises(IntegrityError, match="fk_movie_metadata_movie_id_movies"):
        db_session.commit()


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"runtime": 0}, "runtime_positive"),
        ({"runtime": -10}, "runtime_positive"),
        ({"refresh_status": "auth_failed"}, "refresh_status_valid"),  # Never stored.
        ({"tmdb_validation_status": "probably_ok"}, "tmdb_validation_status_valid"),
    ],
)
def test_metadata_check_constraints(db_session: Session, values, constraint):
    db_session.add(MovieMetadata(movie_id=1, **values))
    with pytest.raises(IntegrityError, match=constraint):
        db_session.commit()


def test_every_status_enum_value_is_accepted_by_the_database(db_session: Session):
    for offset, (refresh, validation) in enumerate(
        zip(RefreshStatus, TmdbIdValidationStatus, strict=False)
    ):
        movie_id = TEST_MOVIES[offset][0]
        db_session.add(
            MovieMetadata(
                movie_id=movie_id, refresh_status=refresh, tmdb_validation_status=validation
            )
        )
    db_session.add(MovieMetadata(movie_id=318, tmdb_validation_status="temporary_error"))
    db_session.commit()


def test_deleting_a_movie_without_user_data_removes_its_metadata(db_session: Session):
    db_session.add(MovieMetadata(movie_id=7, runtime=127))
    db_session.commit()
    db_session.delete(db_session.get(Movie, 7))
    db_session.commit()
    assert db_session.get(MovieMetadata, 7) is None


def test_search_title_follows_the_title(db_session: Session):
    movie = Movie(movie_id=500_001, title="Matrix, The (1999)", genres="Action")
    assert movie.search_title == "matrix the 1999|the matrix"
    db_session.add(movie)
    db_session.commit()
    movie.title = "Léon (1994)"
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(Movie, 500_001).search_title == "leon 1994|leon"
