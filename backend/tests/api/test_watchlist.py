"""API tests for the watchlist endpoints, including cross-user isolation."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import WatchlistItem
from tests.helpers import UNKNOWN_MOVIE_ID

pytestmark = pytest.mark.db

WATCHLIST_URL = "/api/v1/watchlist"


def test_add_movie_returns_201(client: TestClient, alice_headers):
    response = client.put(f"{WATCHLIST_URL}/2571", headers=alice_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["movie_id"] == 2571
    assert set(body) == {"movie_id", "added_at"}


def test_duplicate_addition_returns_200_and_keeps_one_entry(
    client: TestClient, alice_headers, db_session: Session
):
    first = client.put(f"{WATCHLIST_URL}/5", headers=alice_headers).json()
    response = client.put(f"{WATCHLIST_URL}/5", headers=alice_headers)
    assert response.status_code == 200
    assert response.json() == first  # original added_at is preserved
    assert db_session.scalar(select(func.count()).select_from(WatchlistItem)) == 1


def test_list_watchlist(client: TestClient, alice_headers):
    for movie_id in (1, 2, 3):
        client.put(f"{WATCHLIST_URL}/{movie_id}", headers=alice_headers)
    response = client.get(WATCHLIST_URL, headers=alice_headers)
    assert response.status_code == 200
    assert sorted(item["movie_id"] for item in response.json()) == [1, 2, 3]


def test_remove_movie_returns_204(client: TestClient, alice_headers):
    client.put(f"{WATCHLIST_URL}/7", headers=alice_headers)
    response = client.delete(f"{WATCHLIST_URL}/7", headers=alice_headers)
    assert response.status_code == 204
    assert client.get(WATCHLIST_URL, headers=alice_headers).json() == []


def test_remove_non_existent_entry_returns_404(client: TestClient, alice_headers):
    response = client.delete(f"{WATCHLIST_URL}/999", headers=alice_headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not in watchlist"}


@pytest.mark.parametrize("movie_id", ["0", "-5", "abc", "2147483648", "' OR 1=1 --"])
def test_invalid_movie_ids_are_rejected(client: TestClient, alice_headers, movie_id):
    assert client.put(f"{WATCHLIST_URL}/{movie_id}", headers=alice_headers).status_code == 422
    assert client.delete(f"{WATCHLIST_URL}/{movie_id}", headers=alice_headers).status_code == 422


class TestCrossUserIsolation:
    def test_users_cannot_see_each_others_watchlist(
        self, client: TestClient, alice_headers, bob_headers
    ):
        client.put(f"{WATCHLIST_URL}/1", headers=alice_headers)
        assert client.get(WATCHLIST_URL, headers=bob_headers).json() == []

    def test_user_cannot_remove_another_users_entry(
        self, client: TestClient, alice_headers, bob_headers
    ):
        client.put(f"{WATCHLIST_URL}/1", headers=alice_headers)
        assert client.delete(f"{WATCHLIST_URL}/1", headers=bob_headers).status_code == 404
        assert len(client.get(WATCHLIST_URL, headers=alice_headers).json()) == 1

    def test_adding_same_movie_creates_separate_entries_per_user(
        self, client: TestClient, alice_headers, bob_headers
    ):
        assert client.put(f"{WATCHLIST_URL}/1", headers=alice_headers).status_code == 201
        assert client.put(f"{WATCHLIST_URL}/1", headers=bob_headers).status_code == 201


def test_adding_a_movie_outside_the_catalogue_returns_404(
    client: TestClient, alice_headers, db_session: Session
):
    response = client.put(f"{WATCHLIST_URL}/{UNKNOWN_MOVIE_ID}", headers=alice_headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not found"}
    assert db_session.scalar(select(func.count()).select_from(WatchlistItem)) == 0
