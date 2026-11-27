"""API tests for the movie catalogue endpoints.

The database contains the small test catalogue from tests/helpers.py.
Supplementary metadata is inserted directly into movie_metadata, as the
refresh script would do. TMDB is never contacted: the `no_tmdb` fixture makes
any attempt to create a TMDB client during a request fail the test.
"""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.titles import normalize_text
from app.models import Movie, MovieMetadata
from app.services import movie_service, tmdb_service
from tests.helpers import TEST_MOVIES, UNKNOWN_MOVIE_ID

pytestmark = pytest.mark.db

MOVIES_URL = "/api/v1/movies"

MOVIE_FIELDS = {
    "movie_id",
    "title",
    "display_title",
    "year",
    "genres",
    "tmdb_id",
    "imdb_id",
    "movielens_average_rating",
    "movielens_rating_count",
}
# List items (catalogue pages) also carry the stored poster.
SUMMARY_FIELDS = MOVIE_FIELDS | {"poster_url"}
METADATA_FIELDS = {
    "overview",
    "release_date",
    "runtime",
    "poster_path",
    "poster_url",
    "metadata_status",
    "metadata_updated_at",
    "tmdb_validation_status",
}
NULLABLE_METADATA_FIELDS = METADATA_FIELDS - {"metadata_status", "tmdb_validation_status"}
UPDATED_AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_tmdb(monkeypatch):
    """Fail if any code path tries to build a TMDB client during a request."""

    def forbidden(*args, **kwargs):
        raise AssertionError("TMDB must not be contacted by the API")

    monkeypatch.setattr(tmdb_service.TmdbClient, "__init__", forbidden)
    monkeypatch.setattr(tmdb_service, "create_tmdb_client", forbidden)


def store_metadata(db: Session, movie_id: int, **values) -> MovieMetadata:
    """Insert a movie_metadata row as the refresh script would."""
    defaults = {
        "overview": "Led by Woody, Andy's toys live happily in his room...",
        "release_date": date(1995, 10, 30),
        "runtime": 81,
        "poster_path": "/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
        "metadata_source": "tmdb",
        "metadata_updated_at": UPDATED_AT,
        "refresh_status": "ok",
        "refresh_attempted_at": UPDATED_AT,
    }
    row = MovieMetadata(movie_id=movie_id, **(defaults | values))
    db.add(row)
    db.commit()
    return row


def search_ids(client: TestClient, search: str) -> list[int]:
    response = client.get(MOVIES_URL, params={"search": search, "limit": 100})
    assert response.status_code == 200
    return [movie["movie_id"] for movie in response.json()["items"]]


# --- GET /movies ------------------------------------------------------------


def test_list_movies_returns_first_page_with_pagination_info(client: TestClient):
    response = client.get(MOVIES_URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == len(TEST_MOVIES)
    assert (body["limit"], body["offset"]) == (20, 0)
    assert len(body["items"]) == len(TEST_MOVIES)
    assert set(body["items"][0]) == SUMMARY_FIELDS


def collation_order(titles) -> list[str]:
    """Expected title order. PostgreSQL's en_US.utf8 collation ignores accents and
    punctuation at the first comparison level ("Léon" sorts before "Lock"), unlike
    Python's code-point order, so titles are compared in their normalized form."""
    return sorted(titles, key=normalize_text)


def test_list_movies_is_ordered_by_title(client: TestClient):
    titles = [movie["title"] for movie in client.get(MOVIES_URL).json()["items"]]
    assert titles == collation_order(title for _, title, _, _, _ in TEST_MOVIES)


def test_movie_fields_and_genre_list(client: TestClient):
    items = client.get(MOVIES_URL, params={"search": "Toy Story (1995)"}).json()["items"]
    assert items == [
        {
            "movie_id": 1,
            "title": "Toy Story (1995)",
            "display_title": "Toy Story",
            "year": 1995,
            "genres": ["Adventure", "Animation", "Children", "Comedy", "Fantasy"],
            "tmdb_id": 862,
            "imdb_id": 114709,
            "movielens_average_rating": None,
            "movielens_rating_count": None,
            "poster_url": None,  # No metadata stored in this test.
        }
    ]


def test_search_by_partial_title(client: TestClient):
    body = client.get(MOVIES_URL, params={"search": "toy story"}).json()
    assert [m["movie_id"] for m in body["items"]] == [1, 3114, 78499]
    assert body["total"] == 3


def test_search_matches_the_middle_of_a_title(client: TestClient):
    body = client.get(MOVIES_URL, params={"search": "shawshank"}).json()
    assert [m["movie_id"] for m in body["items"]] == [318]


def test_search_without_matches_returns_empty_page(client: TestClient):
    response = client.get(MOVIES_URL, params={"search": "no such movie"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


@pytest.mark.parametrize("search", ["%", "_", "\\", "100%", "!!!", "...", "-", "&&"])
def test_special_characters_are_not_wildcards(client: TestClient, search):
    """% and _ are SQL wildcards; user input must not act as a wildcard.
    Punctuation is ignored by the normalized search, so these find nothing.
    SQL injection attempts are covered by test_search_is_not_vulnerable_to_sql_injection."""
    response = client.get(MOVIES_URL, params={"search": search})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_pagination_returns_consecutive_pages(client: TestClient):
    all_ids = [m["movie_id"] for m in client.get(MOVIES_URL).json()["items"]]
    first = client.get(MOVIES_URL, params={"limit": 5, "offset": 0}).json()
    second = client.get(MOVIES_URL, params={"limit": 5, "offset": 5}).json()
    assert [m["movie_id"] for m in first["items"]] == all_ids[:5]
    assert [m["movie_id"] for m in second["items"]] == all_ids[5:10]
    assert first["total"] == second["total"] == len(TEST_MOVIES)


def test_offset_beyond_the_end_returns_empty_items(client: TestClient):
    body = client.get(MOVIES_URL, params={"offset": 1000}).json()
    assert body["items"] == []
    assert body["total"] == len(TEST_MOVIES)


def test_pagination_with_search(client: TestClient):
    body = client.get(MOVIES_URL, params={"search": "toy", "limit": 2, "offset": 2}).json()
    assert [m["movie_id"] for m in body["items"]] == [78499]
    assert body["total"] == 3


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"limit": "ten"},
        {"offset": -1},
        {"offset": "abc"},
        {"offset": 2_147_483_648},
        {"search": ""},
        {"search": "x" * 101},
    ],
)
def test_invalid_query_parameters_are_rejected(client: TestClient, params):
    assert client.get(MOVIES_URL, params=params).status_code == 422


# --- Normalized search ---------------------------------------------------------


@pytest.mark.parametrize(
    "search", ["matrix", "the matrix", "Matrix, The", "THE MATRIX", "matrix the"]
)
def test_search_handles_movielens_trailing_articles(client: TestClient, search):
    assert search_ids(client, search) == [2571]


@pytest.mark.parametrize("search", ["leon", "Léon", "LEON", "leon the professional", "Leon:"])
def test_search_ignores_accents(client: TestClient, search):
    assert search_ids(client, search) == [293]


@pytest.mark.parametrize(
    "search",
    ["lock stock", "Lock, Stock", "lock stock & two", "lock stock and two", "LOCK-STOCK"],
)
def test_search_ignores_punctuation_differences(client: TestClient, search):
    assert search_ids(client, search) == [2542]


@pytest.mark.parametrize(
    "search", ["TOY STORY", "tOy StOrY", "  toy story  ", "toy  story", "\ttoy story\n"]
)
def test_search_ignores_case_and_whitespace(client: TestClient, search):
    assert search_ids(client, search) == [1, 3114, 78499]


def test_search_finds_alternative_titles_in_parentheses(client: TestClient):
    assert search_ids(client, "cite des enfants perdus") == [29]
    assert search_ids(client, "the city of lost children") == [29]
    assert search_ids(client, "yao a yao") == [30]


def test_search_is_not_vulnerable_to_sql_injection(client: TestClient, db_session: Session):
    for search in ["'; DROP TABLE movies; --", "x' OR '1'='1", "%' OR 1=1 --"]:
        assert client.get(MOVIES_URL, params={"search": search}).json()["total"] == 0
    assert db_session.scalar(select(func.count()).select_from(Movie)) == len(TEST_MOVIES)


def test_search_does_not_change_stored_titles(client: TestClient):
    items = client.get(MOVIES_URL, params={"search": "the matrix"}).json()["items"]
    assert items[0]["title"] == "Matrix, The (1999)"  # Original MovieLens title.


def test_normalized_search_keeps_ordering_and_pagination(client: TestClient):
    everything = search_ids(client, "the")
    assert len(everything) > 3
    pages = [
        client.get(MOVIES_URL, params={"search": "the", "limit": 2, "offset": offset}).json()
        for offset in range(0, len(everything), 2)
    ]
    assert [m["movie_id"] for page in pages for m in page["items"]] == everything
    assert {page["total"] for page in pages} == {len(everything)}
    titles = [m["title"] for page in pages for m in page["items"]]
    assert titles == collation_order(titles)


def test_movie_added_through_the_orm_is_searchable(client: TestClient, db_session: Session):
    db_session.add(Movie(movie_id=500_000, title="Amélie, L' (2001)", genres="Comedy"))
    db_session.commit()
    assert search_ids(client, "lamelie") == [500_000]
    assert search_ids(client, "AMELIE") == [500_000]


# --- GET /movies/{movie_id} -------------------------------------------------


def test_get_movie_by_movielens_id(client: TestClient):
    response = client.get(f"{MOVIES_URL}/2571")
    assert response.status_code == 200
    assert response.json() == {
        "movie_id": 2571,
        "title": "Matrix, The (1999)",
        "display_title": "The Matrix",  # Trailing article moved back for display.
        "year": 1999,
        "genres": ["Action", "Sci-Fi", "Thriller"],
        "tmdb_id": 603,
        "imdb_id": 133093,
        "movielens_average_rating": None,
        "movielens_rating_count": None,
    }


def test_movielens_rating_is_returned_rounded(client: TestClient, db_session):
    movie = db_session.get(Movie, 318)
    movie.movielens_average_rating, movie.movielens_rating_count = 4.410340947332997, 95088
    db_session.commit()
    for url in (f"{MOVIES_URL}/318", f"{MOVIES_URL}/318/details"):
        body = client.get(url).json()
        assert (body["movielens_average_rating"], body["movielens_rating_count"]) == (4.41, 95088)


def test_get_movie_without_tmdb_id(client: TestClient):
    response = client.get(f"{MOVIES_URL}/7842")
    assert response.status_code == 200
    assert response.json()["tmdb_id"] is None


def test_unknown_movie_returns_404(client: TestClient):
    response = client.get(f"{MOVIES_URL}/{UNKNOWN_MOVIE_ID}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not found"}


@pytest.mark.parametrize("movie_id", ["0", "-1", "abc", "1.5", "2147483648"])
def test_invalid_movie_id_is_rejected(client: TestClient, movie_id):
    assert client.get(f"{MOVIES_URL}/{movie_id}").status_code == 422
    assert client.get(f"{MOVIES_URL}/{movie_id}/details").status_code == 422


# --- GET /movies/{movie_id}/details (stored metadata) -----------------------


def test_details_combine_local_data_with_stored_metadata(client: TestClient, db_session):
    store_metadata(db_session, 1, tmdb_validation_status="valid")
    response = client.get(f"{MOVIES_URL}/1/details")

    assert response.status_code == 200
    assert response.json() == {
        "movie_id": 1,
        "title": "Toy Story (1995)",  # MovieLens title kept.
        "display_title": "Toy Story",
        "year": 1995,
        "genres": ["Adventure", "Animation", "Children", "Comedy", "Fantasy"],
        "tmdb_id": 862,
        "imdb_id": 114709,
        "movielens_average_rating": None,
        "movielens_rating_count": None,
        "overview": "Led by Woody, Andy's toys live happily in his room...",
        "release_date": "1995-10-30",
        "runtime": 81,
        "poster_path": "/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
        "poster_url": "https://image.tmdb.org/t/p/w500/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
        "metadata_status": "available",
        "metadata_updated_at": "2026-11-01T12:00:00Z",
        "tmdb_validation_status": "valid",
    }


def test_details_without_imported_metadata(client: TestClient):
    body = client.get(f"{MOVIES_URL}/1/details").json()
    assert body["title"] == "Toy Story (1995)"
    assert body["metadata_status"] == "not_imported"
    assert body["tmdb_validation_status"] == "not_checked"
    assert all(body[field] is None for field in NULLABLE_METADATA_FIELDS)


def test_details_for_movie_without_tmdb_id(client: TestClient):
    response = client.get(f"{MOVIES_URL}/7842/details")
    assert response.status_code == 200
    body = response.json()
    assert (body["title"], body["tmdb_id"]) == ("Dune (2000)", None)
    assert body["metadata_status"] == "no_tmdb_id"
    assert all(body[field] is None for field in NULLABLE_METADATA_FIELDS)


@pytest.mark.parametrize(
    ("refresh_status", "expected"),
    [
        ("not_found", "not_found"),
        ("timeout", "lookup_failed"),
        ("rate_limited", "lookup_failed"),
        ("unavailable", "lookup_failed"),
        ("invalid_response", "lookup_failed"),
    ],
)
def test_details_after_a_failed_first_lookup(client, db_session, refresh_status, expected):
    db_session.add(
        MovieMetadata(movie_id=1, refresh_status=refresh_status, refresh_attempted_at=UPDATED_AT)
    )
    db_session.commit()
    body = client.get(f"{MOVIES_URL}/1/details").json()
    assert body["metadata_status"] == expected
    assert all(body[field] is None for field in NULLABLE_METADATA_FIELDS)  # Nothing invented.


def test_metadata_is_still_shown_after_a_later_failed_refresh(client, db_session):
    store_metadata(db_session, 1, refresh_status="rate_limited")
    body = client.get(f"{MOVIES_URL}/1/details").json()
    assert body["metadata_status"] == "available"
    assert body["runtime"] == 81


def test_missing_poster_gives_null_poster_url(client: TestClient, db_session):
    store_metadata(db_session, 1, poster_path=None, overview=None, runtime=None)
    body = client.get(f"{MOVIES_URL}/1/details").json()
    assert body["metadata_status"] == "available"
    assert (body["poster_path"], body["poster_url"]) == (None, None)  # Frontend placeholder.
    assert body["overview"] is None


def test_validation_result_without_metadata(client: TestClient, db_session):
    db_session.add(MovieMetadata(movie_id=1, tmdb_validation_status="ambiguous"))
    db_session.commit()
    body = client.get(f"{MOVIES_URL}/1/details").json()
    assert body["metadata_status"] == "not_imported"
    assert body["tmdb_validation_status"] == "ambiguous"


def test_details_follow_the_database_across_requests(client: TestClient, db_session):
    assert client.get(f"{MOVIES_URL}/1/details").json()["metadata_status"] == "not_imported"

    row = store_metadata(db_session, 1)
    assert client.get(f"{MOVIES_URL}/1/details").json()["runtime"] == 81

    row.runtime = 82
    db_session.commit()
    assert client.get(f"{MOVIES_URL}/1/details").json()["runtime"] == 82
    # Repeated requests return the same stored data (no external call in between).
    assert (
        client.get(f"{MOVIES_URL}/1/details").json() == client.get(f"{MOVIES_URL}/1/details").json()
    )


def test_details_for_unknown_movie_returns_404(client: TestClient):
    response = client.get(f"{MOVIES_URL}/{UNKNOWN_MOVIE_ID}/details")
    assert response.status_code == 404
    assert response.json() == {"detail": "Movie not found"}


def test_details_have_the_same_fields_in_every_state(client: TestClient, db_session):
    store_metadata(db_session, 1)
    for movie_id in (1, 2, 7842):  # Available, not imported, no TMDB ID.
        body = client.get(f"{MOVIES_URL}/{movie_id}/details").json()
        assert set(body) == MOVIE_FIELDS | METADATA_FIELDS


def test_list_items_show_the_stored_poster_or_null(client: TestClient, db_session):
    """Since the intermediate backend phase, catalogue pages carry the stored
    poster, so a grid needs no /details request per movie (no TMDB call)."""
    store_metadata(db_session, 1)
    items = client.get(MOVIES_URL, params={"search": "toy story"}).json()["items"]
    posters = {item["movie_id"]: item["poster_url"] for item in items}
    assert posters == {
        1: "https://image.tmdb.org/t/p/w500/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
        3114: None,  # No metadata stored: the frontend shows its placeholder.
        78499: None,
    }


# --- GET /movies/genres and the genre filter (intermediate backend phase) ---


def test_genre_list_counts_the_catalogue_genres(client: TestClient):
    response = client.get(f"{MOVIES_URL}/genres")
    assert response.status_code == 200
    expected = Counter(g for _, _, genres, _, _ in TEST_MOVIES for g in genres.split("|"))
    # Ordered by name; IMAX is a MovieLens value, so it is listed (Toy Story 3).
    assert response.json() == [
        {"genre": genre, "movie_count": expected[genre]} for genre in sorted(expected)
    ]
    assert {"genre": "IMAX", "movie_count": 1} in response.json()


def test_genre_filter_combines_with_search_and_rejects_unknown_genres(client: TestClient):
    def ids(**params):
        response = client.get(MOVIES_URL, params={"limit": 100, **params})
        assert response.status_code == 200
        return [movie["movie_id"] for movie in response.json()["items"]], response.json()["total"]

    assert ids(genre="Animation") == ([1, 3114, 78499], 3)
    # "|" boundaries: the last genre of a string matches, and search is ANDed.
    assert ids(genre="IMAX", search="toy story") == ([78499], 1)
    assert ids(genre="Sci-Fi", search="toy story") == ([], 0)

    # Only exact names from /movies/genres are accepted; a part of a name is not.
    for unknown in ("Sci", "drama", "%"):
        response = client.get(MOVIES_URL, params={"genre": unknown})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", "genre"]


# --- GET /movies/featured (intermediate backend phase) ----------------------


def test_featured_movie_rotates_daily_over_complete_validated_metadata(
    client: TestClient, db_session: Session
):
    # Not eligible: no featured movie yet, so the endpoint answers 404.
    store_metadata(db_session, 5, tmdb_validation_status="not_checked")
    store_metadata(db_session, 6, tmdb_validation_status="valid", poster_path=None)
    assert client.get(f"{MOVIES_URL}/featured").status_code == 404

    # Eligible: poster + overview + validated ID.
    store_metadata(db_session, 1, tmdb_validation_status="valid")
    store_metadata(db_session, 2, tmdb_validation_status="valid")

    response = client.get(f"{MOVIES_URL}/featured")
    assert response.status_code == 200
    assert response.json()["movie_id"] in {1, 2}
    assert response.json()["metadata_status"] == "available"

    # Fixed dates: the same movie all day, the other one the next day.
    day = date(2026, 11, 22)
    first = movie_service.get_featured_movie(db_session, day).movie_id
    assert movie_service.get_featured_movie(db_session, day).movie_id == first
    assert (
        movie_service.get_featured_movie(db_session, day + timedelta(days=1)).movie_id
        == ({1, 2} - {first}).pop()
    )


# --- OpenAPI documentation --------------------------------------------------


def test_movie_endpoints_are_documented_in_openapi(client: TestClient):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert {
        "/api/v1/movies",
        "/api/v1/movies/genres",
        "/api/v1/movies/featured",
        "/api/v1/movies/{movie_id}",
        "/api/v1/movies/{movie_id}/details",
    } <= set(paths)

    list_params = {p["name"] for p in paths["/api/v1/movies"]["get"]["parameters"]}
    assert list_params == {"search", "genre", "limit", "offset"}
    assert "404" in paths["/api/v1/movies/{movie_id}/details"]["get"]["responses"]
    components = set(schema["components"]["schemas"])
    assert {"MovieRead", "MovieListResponse", "MovieDetailsRead", "MetadataStatus"} <= components
    # The details endpoint no longer exposes the TMDB client's request status.
    assert "TmdbStatus" not in components
