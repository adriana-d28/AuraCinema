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
    def test_register_stores_hash_not_plaintext(self, db_session: Session, user: User):
        db_session.expire_all()
        stored = db_session.get(User, user.id)
        assert stored.password_hash != PASSWORD
        assert stored.password_hash.startswith("$argon2id$")

    def test_register_duplicate_email_raises(self, db_session: Session, user: User):
        with pytest.raises(auth_service.EmailAlreadyRegisteredError):
            auth_service.register_user(db_session, "svc@example.com", PASSWORD, "Test User")

    def test_concurrent_duplicate_registration_is_caught_by_constraint(
        self, db_session: Session, user: User, monkeypatch
    ):
        """If the pre-check misses a concurrent registration, the unique
        constraint still prevents the duplicate and a clean error is raised."""
        monkeypatch.setattr(auth_service, "get_user_by_email", lambda *args: None)
        with pytest.raises(auth_service.EmailAlreadyRegisteredError):
            auth_service.register_user(db_session, "svc@example.com", PASSWORD, "Test User")
        assert db_session.scalar(select(func.count()).select_from(User)) == 1

    def test_authenticate_with_valid_credentials(self, db_session: Session, user: User):
        assert auth_service.authenticate_user(db_session, "svc@example.com", PASSWORD).id == user.id

    def test_authenticate_normalises_email(self, db_session: Session, user: User):
        assert (
            auth_service.authenticate_user(db_session, "  SVC@Example.com ", PASSWORD) is not None
        )

    def test_authenticate_rejects_wrong_password(self, db_session: Session, user: User):
        assert auth_service.authenticate_user(db_session, "svc@example.com", "wrong") is None

    def test_authenticate_rejects_unknown_email(self, db_session: Session):
        assert auth_service.authenticate_user(db_session, "nobody@example.com", PASSWORD) is None


class TestRatingService:
    def test_upsert_creates_then_updates_single_row(self, db_session: Session, user: User):
        first, created = rating_service.upsert_rating(db_session, user.id, 10, 3.0)
        assert created is True
        second, created = rating_service.upsert_rating(db_session, user.id, 10, 4.5)
        assert created is False
        assert second.id == first.id
        assert second.rating == 4.5
        assert second.rated_at >= first.created_at
        count = db_session.scalar(select(func.count()).select_from(Rating))
        assert count == 1

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

    def test_delete_returns_whether_a_row_was_removed(self, db_session: Session, user: User):
        rating_service.upsert_rating(db_session, user.id, 30, 2.0)
        assert rating_service.delete_rating(db_session, user.id, 30) is True
        assert rating_service.delete_rating(db_session, user.id, 30) is False

    def test_list_is_scoped_to_the_user(self, db_session: Session, user: User):
        other = auth_service.register_user(db_session, "other@example.com", PASSWORD, "Test User")
        rating_service.upsert_rating(db_session, user.id, 1, 4.0)
        rating_service.upsert_rating(db_session, other.id, 2, 3.0)
        assert [r.movie_id for r in rating_service.list_ratings(db_session, user.id)] == [1]


class TestWatchlistService:
    def test_add_is_idempotent(self, db_session: Session, user: User):
        first, created = watchlist_service.add_to_watchlist(db_session, user.id, 5)
        assert created is True
        again, created = watchlist_service.add_to_watchlist(db_session, user.id, 5)
        assert created is False
        assert again.id == first.id
        assert again.added_at == first.added_at
        assert db_session.scalar(select(func.count()).select_from(WatchlistItem)) == 1

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

    def test_remove_returns_whether_a_row_was_removed(self, db_session: Session, user: User):
        watchlist_service.add_to_watchlist(db_session, user.id, 5)
        assert watchlist_service.remove_from_watchlist(db_session, user.id, 5) is True
        assert watchlist_service.remove_from_watchlist(db_session, user.id, 5) is False

    def test_remove_does_not_touch_other_users(self, db_session: Session, user: User):
        other = auth_service.register_user(db_session, "other@example.com", PASSWORD, "Test User")
        watchlist_service.add_to_watchlist(db_session, other.id, 5)
        assert watchlist_service.remove_from_watchlist(db_session, user.id, 5) is False
        assert len(watchlist_service.list_watchlist(db_session, other.id)) == 1
