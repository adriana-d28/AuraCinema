"""API tests for the ratings endpoints, including cross-user isolation."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import MovieMetadata, Rating
from tests.helpers import UNKNOWN_MOVIE_ID

pytestmark = pytest.mark.db

RATINGS_URL = "/api/v1/ratings"
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def put_rating(client: TestClient, headers, movie_id, value):
    return client.put(f"{RATINGS_URL}/{movie_id}", json={"rating": value}, headers=headers)


def test_create_rating_returns_201(client: TestClient, alice_headers):
    response = put_rating(client, alice_headers, 318, 4.5)
    assert response.status_code == 201
    body = response.json()
    assert body["movie_id"] == 318
    assert body["rating"] == 4.5
    assert set(body) == {"movie_id", "rating", "created_at", "rated_at", "movie"}


def test_ratings_include_the_movie_summary(client: TestClient, alice_headers, db_session):
    """Intermediate backend phase: each rating carries the movie as shown in
    lists (title, display title, poster), so no request per movie is needed."""
    db_session.add(MovieMetadata(movie_id=2571, poster_path="/m.jpg", metadata_updated_at=NOW))
    db_session.commit()
    put_rating(client, alice_headers, 2571, 5.0)
    put_rating(client, alice_headers, 7842, 3.0)

    movies = [r["movie"] for r in client.get(RATINGS_URL, headers=alice_headers).json()]
    assert [(m["movie_id"], m["display_title"], m["poster_url"]) for m in movies] == [
        (7842, "Dune", None),  # Most recently rated first; no metadata: placeholder.
        (2571, "The Matrix", "https://image.tmdb.org/t/p/w500/m.jpg"),
    ]


def test_update_rating_returns_200_without_creating_duplicates(
    client: TestClient, alice_headers, db_session: Session
):
    created = put_rating(client, alice_headers, 318, 3.0).json()
    response = put_rating(client, alice_headers, 318, 5.0)
    assert response.status_code == 200
    updated = response.json()
    assert updated["rating"] == 5.0
    assert updated["created_at"] == created["created_at"]
    assert updated["rated_at"] >= created["rated_at"]
    assert db_session.scalar(select(func.count()).select_from(Rating)) == 1


def test_list_ratings_returns_only_current_users_ratings(client: TestClient, alice_headers):
    put_rating(client, alice_headers, 1, 4.0)
    put_rating(client, alice_headers, 2, 2.5)
    response = client.get(RATINGS_URL, headers=alice_headers)
    assert response.status_code == 200
    assert sorted(r["movie_id"] for r in response.json()) == [1, 2]


def test_list_ratings_is_empty_for_new_user(client: TestClient, alice_headers):
    assert client.get(RATINGS_URL, headers=alice_headers).json() == []


def test_delete_rating_returns_204_then_404(client: TestClient, alice_headers):
    put_rating(client, alice_headers, 1, 4.0)
    first = client.delete(f"{RATINGS_URL}/1", headers=alice_headers)
    assert first.status_code == 204
    assert first.content == b""
    second = client.delete(f"{RATINGS_URL}/1", headers=alice_headers)
    assert second.status_code == 404
    assert second.json() == {"detail": "Rating not found"}
    assert client.get(RATINGS_URL, headers=alice_headers).json() == []


# Two values are enough to prove the schema is applied to the route; the full
# range/step/type rules are covered by tests/unit/test_schemas.py.
@pytest.mark.parametrize("value", [5.5, "abc"])
def test_invalid_rating_values_are_rejected(client: TestClient, alice_headers, value):
    assert put_rating(client, alice_headers, 1, value).status_code == 422


@pytest.mark.parametrize("movie_id", ["0", "-1", "abc", "1.5", "2147483648", "1;DROP TABLE users"])
def test_invalid_movie_ids_are_rejected(client: TestClient, alice_headers, movie_id):
    put_response = put_rating(client, alice_headers, movie_id, 4.0)
    delete_response = client.delete(f"{RATINGS_URL}/{movie_id}", headers=alice_headers)
    assert put_response.status_code == 422
    assert delete_response.status_code == 422


def test_missing_body_and_missing_field_are_rejected(client: TestClient, alice_headers):
    assert client.put(f"{RATINGS_URL}/1", headers=alice_headers).status_code == 422
    assert client.put(f"{RATINGS_URL}/1", json={}, headers=alice_headers).status_code == 422


def test_malformed_json_is_rejected(client: TestClient, alice_headers):
    response = client.put(
        f"{RATINGS_URL}/1",
        content='{"rating": 4.',
        headers={**alice_headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_client_cannot_set_user_id_in_body(client: TestClient, alice_headers):
    """Ownership comes from the token; a user_id in the body is rejected."""
    response = client.put(
        f"{RATINGS_URL}/1", json={"rating": 4.0, "user_id": 2}, headers=alice_headers
    )
    assert response.status_code == 422


class TestCrossUserIsolation:
    def test_users_cannot_see_each_others_ratings(
        self, client: TestClient, alice_headers, bob_headers
    ):
        put_rating(client, alice_headers, 1, 4.0)
        assert client.get(RATINGS_URL, headers=bob_headers).json() == []

    def test_user_cannot_delete_another_users_rating(
        self, client: TestClient, alice_headers, bob_headers
    ):
        put_rating(client, alice_headers, 1, 4.0)
        response = client.delete(f"{RATINGS_URL}/1", headers=bob_headers)
        assert response.status_code == 404
        assert len(client.get(RATINGS_URL, headers=alice_headers).json()) == 1

    def test_rating_same_movie_does_not_overwrite_another_users_rating(
        self, client: TestClient, alice_headers, bob_headers
    ):
        put_rating(client, alice_headers, 1, 4.0)
        response = put_rating(client, bob_headers, 1, 1.0)
        assert response.status_code == 201  # Bob gets his own new rating
        assert client.get(RATINGS_URL, headers=alice_headers).json()[0]["rating"] == 4.0
        assert client.get(RATINGS_URL, headers=bob_headers).json()[0]["rating"] == 1.0


def test_rating_a_movie_outside_the_catalogue_returns_404(
    client: TestClient, alice_headers, db_session: Session
):
    response = put_rating(client, alice_headers, UNKNOWN_MOVIE_ID, 4.0)
    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not found"}
    assert db_session.scalar(select(func.count()).select_from(Rating)) == 0


def test_movie_without_tmdb_id_can_be_rated(client: TestClient, alice_headers):
    assert put_rating(client, alice_headers, 7842, 3.5).status_code == 201
