"""Movie catalogue endpoints.

These endpoints are public (no login required): browsing the catalogue does
not involve any user's data, in the same way as the health endpoints. All
user-specific endpoints (ratings, watchlist) still require a token.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, get_movie_or_404
from app.schemas.common import POSTGRES_INT_MAX, MovieIdPath
from app.schemas.movie import MovieDetailsRead, MovieListResponse, MovieRead
from app.services import movie_service

router = APIRouter(prefix="/movies", tags=["movies"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
SEARCH_MAX_LENGTH = 100

MOVIE_NOT_FOUND = {404: {"description": "Movie not found in the catalogue"}}


@router.get("", response_model=MovieListResponse, summary="List or search movies")
def list_movies(
    db: DbSession,
    search: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=SEARCH_MAX_LENGTH,
            description=(
                "Partial match on the title, ignoring case, accents and punctuation, "
                "e.g. 'toy story', 'the matrix' or 'leon'"
            ),
        ),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Page size (1-100)")
    ] = DEFAULT_PAGE_SIZE,
    offset: Annotated[
        int, Query(ge=0, le=POSTGRES_INT_MAX, description="Number of results to skip")
    ] = 0,
) -> MovieListResponse:
    # Surrounding spaces are ignored; a search of only spaces lists everything.
    search_text = search.strip() if search else None
    movies, total = movie_service.list_movies(db, search_text or None, limit, offset)
    return MovieListResponse(
        items=[MovieRead.from_movie(movie) for movie in movies],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{movie_id}",
    response_model=MovieRead,
    summary="Get a movie from the local catalogue",
    responses=MOVIE_NOT_FOUND,
)
def get_movie(movie_id: MovieIdPath, db: DbSession) -> MovieRead:
    # Local data only: TMDB is not contacted by this endpoint.
    return MovieRead.from_movie(get_movie_or_404(db, movie_id))


@router.get(
    "/{movie_id}/details",
    response_model=MovieDetailsRead,
    summary="Get a movie with its stored supplementary metadata (overview, poster)",
    responses=MOVIE_NOT_FOUND,
)
def get_movie_details(movie_id: MovieIdPath, db: DbSession) -> MovieDetailsRead:
    """Returns 200 whenever the movie exists locally. The metadata comes from
    the local movie_metadata table (TMDB is never called during a request). If
    no metadata is stored, the metadata fields are null and `metadata_status`
    explains why."""
    movie = get_movie_or_404(db, movie_id)
    return movie_service.get_movie_details(movie)
