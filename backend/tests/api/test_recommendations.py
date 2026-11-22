"""API tests for GET /api/v1/recommendations.

The loaded models are replaced through FastAPI's dependency_overrides by fake
recommenders with fixed outputs, which also record what the endpoint passed to
them. This checks the HTTP contract (authentication, user isolation, query
validation, response format, error status) independently of the real models.

Already covered elsewhere and not repeated: missing token (test_auth.py, which
now includes this endpoint), invalid/expired tokens and deleted accounts (the
same get_current_user dependency, test_auth.py), duplicate/unknown IDs and
posters (test_recommendation_support.py), the cold-start boundary cases
(test_recommendation_service.py).
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.recommendation_service import (
    COLD_START_MESSAGE,
    Recommenders,
    load_recommenders,
)

pytestmark = pytest.mark.db

URL = "/api/v1/recommendations"


@pytest.fixture
def calls(client: TestClient):
    """Install fake recommenders and return a dict recording their calls."""
    received: dict = {}

    def fake_cf(history, n):
        received["cf"] = (dict(history), n)
        return [(2571, 2.41), (3114, 1.7), (1, 0.9)]

    def fake_popularity(n, exclude_movie_ids):
        received["popularity"] = (n, set(exclude_movie_ids))
        return [(318, 90467.0), (2571, 86183.0)]

    app.dependency_overrides[load_recommenders] = lambda: Recommenders(fake_cf, fake_popularity)
    yield received
    app.dependency_overrides.pop(load_recommenders, None)


def rate(client: TestClient, headers, ratings: dict[int, float]) -> None:
    for movie_id, value in ratings.items():
        url = f"/api/v1/ratings/{movie_id}"
        assert client.put(url, json={"rating": value}, headers=headers).status_code == 201


def test_new_user_gets_popular_movies_with_the_cold_start_message(
    client: TestClient, alice_headers, calls
):
    response = client.get(URL, headers=alice_headers)
    assert response.status_code == 200
    assert response.json() == {
        "source": "popularity",
        "personalized": False,
        "message": COLD_START_MESSAGE,
        "items": [
            {
                "movie_id": 318,
                "title": "Shawshank Redemption, The (1994)",
                # Added in the intermediate backend phase (inherited from MovieRead).
                "display_title": "The Shawshank Redemption",
                "year": 1994,
                "genres": ["Crime", "Drama"],
                "tmdb_id": 278,
                "imdb_id": 111161,
                "rank": 1,
                "score": 90467.0,
                "poster_url": None,
            },
            {
                "movie_id": 2571,
                "title": "Matrix, The (1999)",
                "display_title": "The Matrix",
                "year": 1999,
                "genres": ["Action", "Sci-Fi", "Thriller"],
                "tmdb_id": 603,
                "imdb_id": 133093,
                "rank": 2,
                "score": 86183.0,
                "poster_url": None,
            },
        ],
    }
    assert calls["popularity"] == (10, set())  # default limit, nothing to exclude


def test_personalised_recommendations_use_only_the_callers_ratings(
    client: TestClient, alice_headers, bob_headers, calls
):
    rate(client, alice_headers, {1: 5.0, 318: 2.0})
    rate(client, bob_headers, {2: 4.0, 3: 1.0, 5: 3.5})
    # Alice keeps a movie on her watchlist: it must remain recommendable.
    assert client.put("/api/v1/watchlist/2571", headers=alice_headers).status_code == 201

    # A user_id parameter is not part of the API and is ignored: the token decides.
    response = client.get(URL, params={"limit": 5, "user_id": 2}, headers=alice_headers)

    assert response.status_code == 200
    body = response.json()
    assert calls["cf"] == ({1: 5.0, 318: 2.0}, 5)  # Alice's ratings only, never Bob's
    assert (body["source"], body["personalized"], body["message"]) == (
        "collaborative_filtering",
        True,
        None,
    )
    # Order and ranks follow the model; the rated movie 1 is removed; 2571 (watchlist) stays.
    assert [(item["rank"], item["movie_id"]) for item in body["items"]] == [(1, 2571), (2, 3114)]


@pytest.mark.parametrize("limit", ["0", "21", "-1", "ten", "2.5"])
def test_invalid_limit_is_rejected(client: TestClient, alice_headers, calls, limit):
    response = client.get(URL, params={"limit": limit}, headers=alice_headers)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "limit"]


def test_missing_model_returns_503_without_internal_details(client: TestClient, alice_headers):
    app.dependency_overrides[load_recommenders] = lambda: Recommenders(None, None)
    try:
        response = client.get(URL, headers=alice_headers)
    finally:
        app.dependency_overrides.pop(load_recommenders, None)
    assert response.status_code == 503
    assert response.json() == {"detail": "Recommendations are temporarily unavailable"}
