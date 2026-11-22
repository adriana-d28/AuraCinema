"""Movie catalogue endpoints.

These endpoints are public (no login required): browsing the catalogue does
not involve any user's data, in the same way as the health endpoints. All
user-specific endpoints (ratings, watchlist) still require a token.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError

from app.api.deps import DbSession, get_movie_or_404
from app.schemas.common import POSTGRES_INT_MAX, MovieIdPath
from app.schemas.movie import GenreRead, MovieDetailsRead, MovieListResponse, MovieRead
from app.services import movie_service

router = APIRouter(prefix="/movies", tags=["movies"])

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20
SEARCH_MAX_LENGTH = 100
# The longest MovieLens genre name ("Documentary") has 11 characters; 50 only
# rejects absurd values before the catalogue is queried.
GENRE_MAX_LENGTH = 50

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
    genre: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=GENRE_MAX_LENGTH,
            description=(
                "Only movies with this genre, written exactly as returned by "
                "GET /movies/genres (e.g. 'Sci-Fi'). Can be combined with search."
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
    # An unknown genre is a client mistake (the valid names come from
    # /movies/genres), so it is reported as a 422 in the usual validation
    # format instead of silently returning an empty page.
    if genre is not None and genre not in {g.genre for g in movie_service.catalogue_genres(db)}:
        raise RequestValidationError(
            [{"loc": ("query", "genre"), "msg": "Unknown genre", "type": "value_error"}]
        )
    # Surrounding spaces are ignored; a search of only spaces lists everything.
    search_text = search.strip() if search else None
    movies, total = movie_service.list_movies(db, search_text or None, limit, offset, genre)
    return MovieListResponse(
        # Each item carries its stored poster, so a grid needs no extra requests.
        items=[movie_service.build_movie_summary(movie) for movie in movies],
        total=total,
        limit=limit,
        offset=offset,
    )


# The two fixed paths below must be declared BEFORE "/{movie_id}": FastAPI
# tries routes in order, and "/{movie_id}" would otherwise take "genres" as a
# movie ID and answer 422.


@router.get("/genres", response_model=list[GenreRead], summary="List the catalogue genres")
def list_genres(db: DbSession) -> list[GenreRead]:
    """Every genre used in the catalogue, ordered by name, with its number of
    movies. The names are the values accepted by the `genre` filter."""
    return movie_service.catalogue_genres(db)


@router.get(
    "/featured",
    response_model=MovieDetailsRead,
    summary="Get today's featured movie (Discover)",
    responses={404: {"description": "No movie qualifies (metadata not imported yet)"}},
)
def get_featured_movie(db: DbSession) -> MovieDetailsRead:
    """A catalogue highlight that changes once a day (UTC). It is a simple
    rotation over movies with a poster, an overview and a validated TMDB ID;
    it is not based on popularity or on any user's ratings."""
    movie = movie_service.get_featured_movie(db, datetime.now(UTC).date())
    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No featured movie available"
        )
    return movie_service.get_movie_details(movie)


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
