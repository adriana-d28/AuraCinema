"""Tests for the recommendation service (app/services/recommendation_service.py).

The ML models are replaced by small fake functions with fixed outputs, so these
tests check the service's own logic (history, cold-start rule, filtering, error
handling) without loading or running a real model. One final test loads the real
versioned model files from ml/data/models, to prove that the backend can use them.

Already covered elsewhere and therefore not repeated here: removal of duplicate
and unknown movie IDs, rank numbering and missing posters
(tests/integration/test_recommendation_support.py).
"""

from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from app.models import User
from app.schemas.recommendation import RecommendationSource
from app.services import auth_service, rating_service, recommendation_service
from app.services.recommendation_service import (
    COLD_START_MESSAGE,
    MODEL_DIR,
    RecommendationUnavailableError,
    Recommenders,
    get_rating_history,
    has_enough_history_for_cf,
    recommend_for_user,
)

PASSWORD = "service-test-password"


def must_not_be_called(*args, **kwargs):
    raise AssertionError("this recommender must not be used for this user")


@pytest.fixture
def user(db_session: Session) -> User:
    return auth_service.register_user(db_session, "reco@example.com", PASSWORD, "Test User")


def rate(db: Session, user: User, ratings: dict[int, float]) -> None:
    for movie_id, value in ratings.items():
        rating_service.upsert_rating(db, user.id, movie_id, value)


# --- Cold-start rule (pure logic, no database) -----------------------------------


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ({}, False),  # no ratings
        ({1: 4.0}, False),  # one rating: its deviation from the mean is always 0
        ({1: 4.0, 2: 4.0}, False),  # threshold reached, but all ratings identical
        ({1: 4.0, 2: 3.0}, True),  # exactly at the threshold, with varied ratings
        ({1: 4.0, 2: 3.0, 3: 5.0}, True),  # above the threshold
    ],
)
def test_cold_start_rule(history, expected):
    assert recommendation_service.MIN_RATINGS_FOR_CF == 2  # the documented value
    assert has_enough_history_for_cf(history) is expected


# --- Service with the database and fake recommenders -----------------------------


@pytest.mark.db
def test_rating_history_holds_only_this_users_current_ratings(db_session: Session, user: User):
    other = auth_service.register_user(db_session, "other@example.com", PASSWORD, "Test User")
    rate(db_session, user, {1: 4.5, 318: 3.0})
    rate(db_session, user, {318: 5.0})  # re-rating replaces the old value
    rate(db_session, other, {2571: 1.0})
    assert get_rating_history(db_session, user.id) == {1: 4.5, 318: 5.0}
    assert get_rating_history(db_session, 999_999) == {}


@pytest.mark.db
def test_user_with_enough_history_gets_collaborative_filtering(db_session: Session, user: User):
    rate(db_session, user, {1: 5.0, 318: 2.0})
    received = {}

    def fake_cf(history, n):
        received.update(history=dict(history), n=n)
        # 318 is already rated: the service must drop it even if a model returned it.
        return [(2571, 2.4), (318, 2.0), (3114, 1.1)]

    response = recommend_for_user(db_session, user.id, 5, Recommenders(fake_cf, must_not_be_called))

    assert received == {"history": {1: 5.0, 318: 2.0}, "n": 5}
    assert response.source == RecommendationSource.COLLABORATIVE_FILTERING
    assert response.personalized is True and response.message is None
    assert [(m.rank, m.movie_id, m.score) for m in response.items] == [
        (1, 2571, 2.4),
        (2, 3114, 1.1),
    ]


@pytest.mark.db
@pytest.mark.parametrize("ratings", [{}, {1: 4.0}, {1: 4.0, 2: 4.0}])
def test_cold_start_user_gets_popularity_without_rated_movies(
    db_session: Session, user: User, ratings
):
    rate(db_session, user, ratings)
    received = {}

    def fake_popularity(n, exclude_movie_ids):
        received.update(n=n, excluded=set(exclude_movie_ids))
        return [(318, 90000.0), (2571, 86000.0)]

    response = recommend_for_user(
        db_session, user.id, 10, Recommenders(must_not_be_called, fake_popularity)
    )

    assert received == {"n": 10, "excluded": set(ratings)}
    assert response.source == RecommendationSource.POPULARITY
    assert response.personalized is False and response.message == COLD_START_MESSAGE
    assert [m.movie_id for m in response.items] == [318, 2571]


@pytest.mark.db
def test_missing_model_is_an_error_and_never_replaced_by_the_other_model(
    db_session: Session, user: User
):
    # CF not loaded: a user who needs CF gets an error, not the popularity list...
    rate(db_session, user, {1: 5.0, 318: 2.0})
    with pytest.raises(RecommendationUnavailableError):
        recommend_for_user(db_session, user.id, 10, Recommenders(None, must_not_be_called))

    # ...and the same in the other direction for a cold-start user.
    newcomer = auth_service.register_user(db_session, "new@example.com", PASSWORD, "Test User")
    with pytest.raises(RecommendationUnavailableError):
        recommend_for_user(db_session, newcomer.id, 10, Recommenders(must_not_be_called, None))


@pytest.mark.db
def test_no_remaining_candidates_gives_an_empty_list(db_session: Session, user: User):
    rate(db_session, user, {1: 5.0, 318: 2.0})
    response = recommend_for_user(
        db_session, user.id, 10, Recommenders(lambda history, n: [], must_not_be_called)
    )
    assert response.items == []


# --- Loading the model files -----------------------------------------------------


def test_a_model_that_fails_to_load_is_reported_and_left_unavailable(monkeypatch, caplog):
    def broken_cf_loader(model_dir, processed_dir):
        raise ValueError("cf_item_neighbours.npz does not match the hash in the manifest")

    def working_popularity_loader(model_dir):
        ranking = pd.DataFrame({"movieId": [318], "rating_count": [95088]})
        return ranking, {"baseline": {"version": "1.0.0"}}

    fake_cf_module = SimpleNamespace(load_cf_model=broken_cf_loader, recommend_movies=None)
    fake_popularity_module = SimpleNamespace(
        load_popularity_baseline=working_popularity_loader,
        top_n_popular_movies=lambda ranking, n, exclude_movie_ids=None: [(318, 1.0)],
    )
    fake_discovery_module = SimpleNamespace(rerank=lambda *args, rating_counts: rating_counts)
    monkeypatch.setattr(
        recommendation_service,
        "_import_ml_modules",
        lambda: (fake_cf_module, fake_popularity_module, fake_discovery_module),
    )

    # __wrapped__ is the original function behind lru_cache, so this test neither
    # uses nor changes the models cached for the rest of the test session.
    recommenders = recommendation_service.load_recommenders.__wrapped__()

    assert recommenders.cf is None  # unavailable, not replaced by popularity
    assert recommenders.popularity(1, exclude_movie_ids=set()) == [(318, 1.0)]
    # Discovery Mode is loaded with the baseline's rating counts (used for novelty).
    assert recommenders.discovery() == {318: 95088}
    assert "Could not load the collaborative filtering model" in caplog.text


# --- The real committed model files ----------------------------------------------


RUNTIME_FILES = [
    "cf_item_neighbours.npz",
    "cf_model_manifest.json",
    "movie_index_map.csv",
    "popularity_baseline.csv",
    "popularity_baseline_manifest.json",
]


def test_real_model_files_load_and_recommend():
    # Every runtime file is versioned in ml/data/models; nothing comes from the
    # git-ignored ml/data/processed folder (training/test data), so this test
    # also runs in a fresh clone.
    assert all((MODEL_DIR / name).is_file() for name in RUNTIME_FILES)
    recommenders = recommendation_service.load_recommenders()
    assert recommenders.cf is not None and recommenders.popularity is not None

    history = {541: 5.0, 1136: 1.0, 32: 5.0}
    cf_results = recommenders.cf(history, 10)
    popular = recommenders.popularity(10, exclude_movie_ids={318})
    assert len(cf_results) == 10 and not set(history) & {m for m, _ in cf_results}
    assert len(popular) == 10 and 318 not in {m for m, _ in popular}
    # Only plain (movieId, score) pairs leave the ML component.
    assert all(isinstance(m, int) and isinstance(s, float) for m, s in cf_results + popular)

    # Discovery Mode re-ranks the same pool size as its offline evaluation.
    from src.discovery_mode import CANDIDATE_POOL

    assert recommendation_service.DISCOVERY_CANDIDATES == CANDIDATE_POOL
    candidates = recommenders.cf(history, CANDIDATE_POOL)
    adventurous = recommenders.discovery(candidates, 10, "adventurous", {})
    assert len(adventurous) == 10 and set(adventurous) <= set(candidates)
