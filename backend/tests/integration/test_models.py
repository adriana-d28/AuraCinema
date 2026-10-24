"""Integration tests for ORM models and database constraints on PostgreSQL.

These tests insert data directly through the ORM (bypassing the API) to prove
that the database itself enforces the integrity rules.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Rating, User, WatchlistItem

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


def test_two_users_can_rate_the_same_movie(db_session: Session):
    alice = create_user(db_session, "alice@example.com")
    bob = create_user(db_session, "bob@example.com")
    db_session.add_all(
        [
            Rating(user_id=alice.id, movie_id=1, rating=3.0),
            Rating(user_id=bob.id, movie_id=1, rating=5.0),
        ]
    )
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Rating)) == 2


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


def test_rating_update_modifies_the_existing_row(db_session: Session):
    user = create_user(db_session)
    rating = Rating(user_id=user.id, movie_id=1, rating=2.0)
    db_session.add(rating)
    db_session.commit()

    rating.rating = 4.0
    db_session.commit()
    db_session.expire_all()

    rows = db_session.scalars(select(Rating).where(Rating.user_id == user.id)).all()
    assert len(rows) == 1
    assert rows[0].rating == 4.0


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
