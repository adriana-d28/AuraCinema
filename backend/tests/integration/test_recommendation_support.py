"""Tests for the preparatory recommendation helper (no recommendation model yet).

movie_service.build_recommended_movies turns a recommender's ranked list of
(MovieLens movieId, score) pairs into response objects.
"""

import pytest
from sqlalchemy.orm import Session

from app.models import MovieMetadata
from app.schemas.movie import RecommendedMovieRead
from app.services.movie_service import build_recommended_movies, get_movies_by_ids
from tests.helpers import UNKNOWN_MOVIE_ID

pytestmark = pytest.mark.db


def test_order_and_scores_from_the_recommender_are_kept(db_session: Session):
    results = build_recommended_movies(db_session, [(2571, 0.93), (1, 0.81), (318, 0.42)])
    assert [(r.rank, r.movie_id, r.score) for r in results] == [
        (1, 2571, 0.93),
        (2, 1, 0.81),
        (3, 318, 0.42),
    ]
    assert results[0].title == "Matrix, The (1999)"
    assert results[0].genres == ["Action", "Sci-Fi", "Thriller"]


def test_ids_outside_the_catalogue_are_dropped_and_ranks_stay_consecutive(db_session: Session):
    results = build_recommended_movies(db_session, [(UNKNOWN_MOVIE_ID, 0.99), (1, 0.5), (1, 0.4)])
    assert [(r.rank, r.movie_id) for r in results] == [(1, 1)]  # Unknown and repeated IDs removed.


def test_stored_poster_is_included_when_available(db_session: Session):
    db_session.add(MovieMetadata(movie_id=1, poster_path="/toy.jpg"))
    db_session.commit()
    results = build_recommended_movies(db_session, [(1, 1.0), (2, 0.9)])
    assert results[0].poster_url == "https://image.tmdb.org/t/p/w500/toy.jpg"
    assert results[1].poster_url is None  # No metadata: the frontend shows a placeholder.


def test_empty_recommendation_list(db_session: Session):
    assert build_recommended_movies(db_session, []) == []
    assert get_movies_by_ids(db_session, []) == {}


def test_internal_model_indices_are_not_part_of_the_schema():
    fields = set(RecommendedMovieRead.model_fields)
    assert "item_index" not in fields
    assert {"movie_id", "title", "genres", "rank", "score", "poster_url"} <= fields
