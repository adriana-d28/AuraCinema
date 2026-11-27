"""Integration tests for the service layer against the PostgreSQL test database."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Rating, User, WatchlistItem
from app.services import auth_service, rating_service, watchlist_service

pytestmark = pytest.mark.db

PASSWORD = "service-test-password"


@pytest.fixture
def user(db_session: Session) -> User:
    return auth_service.register_user(db_session, "svc@example.com", PASSWORD, "Test User")


class TestAuthService:
    def test_concurrent_duplicate_registration_is_caught_by_constraint(
        self, db_session: Session, user: User, monkeypatch
    ):
        """If the pre-check misses a concurrent registration, the unique
        constraint still prevents the duplicate and a clean error is raised."""
        monkeypatch.setattr(auth_service, "get_user_by_email", lambda *args: None)
        with pytest.raises(auth_service.EmailAlreadyRegisteredError):
            auth_service.register_user(db_session, "svc@example.com", PASSWORD, "Test User")
        assert db_session.scalar(select(func.count()).select_from(User)) == 1


class TestRatingService:
    def test_upsert_recovers_from_concurrent_insert(
        self, db_session: Session, user: User, monkeypatch
    ):
        """Simulates another request inserting the same rating between our
        SELECT and INSERT: the unique constraint fires and the service falls
        back to updating the existing row instead of failing."""
        db_session.add(Rating(user_id=user.id, movie_id=20, rating=1.0))
        db_session.commit()

        real_get_rating = rating_service.get_rating
        calls = {"count": 0}

        def stale_first_lookup(*args, **kwargs):
            calls["count"] += 1
            return None if calls["count"] == 1 else real_get_rating(*args, **kwargs)

        monkeypatch.setattr(rating_service, "get_rating", stale_first_lookup)
        rating, created = rating_service.upsert_rating(db_session, user.id, 20, 5.0)

        assert created is False
        assert rating.rating == 5.0
        assert db_session.scalar(select(func.count()).select_from(Rating)) == 1


class TestWatchlistService:
    def test_add_recovers_from_concurrent_insert(
        self, db_session: Session, user: User, monkeypatch
    ):
        db_session.add(WatchlistItem(user_id=user.id, movie_id=6))
        db_session.commit()

        real_get_item = watchlist_service.get_watchlist_item
        calls = {"count": 0}

        def stale_first_lookup(*args, **kwargs):
            calls["count"] += 1
            return None if calls["count"] == 1 else real_get_item(*args, **kwargs)

        monkeypatch.setattr(watchlist_service, "get_watchlist_item", stale_first_lookup)
        item, created = watchlist_service.add_to_watchlist(db_session, user.id, 6)

        assert created is False
        assert item.movie_id == 6
        assert db_session.scalar(select(func.count()).select_from(WatchlistItem)) == 1
