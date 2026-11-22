"""Business logic for the movie catalogue.

The local PostgreSQL catalogue is the source of truth for movie IDs, titles
and genres. Supplementary metadata (overview, poster, ...) is read from the
local movie_metadata table, which is filled by maintenance scripts. Normal
requests therefore never depend on TMDB being available.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.titles import normalize_text
from app.models.movie import Movie, split_genres
from app.models.movie_metadata import MovieMetadata, RefreshStatus, TmdbIdValidationStatus
from app.schemas.movie import (
    GenreRead,
    MetadataStatus,
    MovieDetailsRead,
    MovieRead,
    MovieSummaryRead,
    RecommendedMovieRead,
)
from app.services.tmdb_service import build_poster_url


def _escape_like(text: str) -> str:
    """Make %, _ and \\ match literally inside a LIKE pattern (defence in depth:
    normalized text contains only letters, digits and spaces)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_movies(
    db: Session, search: str | None, limit: int, offset: int, genre: str | None = None
) -> tuple[list[Movie], int]:
    """Return one page of movies and the total number of matches.

    `search` is normalized like the stored search_title (lower case, no
    accents or punctuation, see app.core.titles) and matched as a "contains"
    condition, so "the matrix", "MATRIX" and "matrix, the" all find
    "Matrix, The (1999)". A search made only of punctuation matches nothing.

    `genre` keeps only movies that have exactly that MovieLens genre. It must
    be one of catalogue_genres() (the route checks this). Search and genre can
    be combined; both conditions must then hold.

    Results are ordered by title, then movie_id, so pages are stable. Only the
    requested page is loaded from the database, together with the stored
    metadata of those movies (one extra query), so list items can show posters.
    """
    statement = select(Movie)
    count_statement = select(func.count()).select_from(Movie)
    if search:
        normalized = normalize_text(search)
        if not normalized:
            return [], 0
        condition = Movie.search_title.like(f"%{_escape_like(normalized)}%", escape="\\")
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)
    if genre:
        # genres is stored in the MovieLens format "Action|Sci-Fi|Thriller".
        # Adding a "|" on both sides lets one pattern match the first, a middle
        # or the last genre, and never a part of another genre's name.
        # The value is a bound parameter, so it can never act as SQL.
        condition = func.concat("|", Movie.genres, "|").like(
            f"%|{_escape_like(genre)}|%", escape="\\"
        )
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = db.scalar(count_statement) or 0
    page = db.scalars(
        statement.options(selectinload(Movie.movie_metadata))
        .order_by(Movie.title, Movie.movie_id)
        .limit(limit)
        .offset(offset)
    )
    return list(page), total


def build_movie_summary(movie: Movie) -> MovieSummaryRead:
    """Catalogue data plus the stored poster, for list items.

    Uses the same poster rule as the recommendation list: the stored
    poster_path, or null (placeholder) when nothing is stored.
    """
    metadata = movie.movie_metadata
    poster_path = metadata.poster_path if metadata is not None else None
    return MovieSummaryRead(
        **MovieRead.from_movie(movie).model_dump(), poster_url=build_poster_url(poster_path)
    )


def catalogue_genres(db: Session) -> list[GenreRead]:
    """Every genre used in the catalogue, with its number of movies, by name.

    The genres are read from the catalogue itself instead of a fixed list, so
    they always match the imported MovieLens data. The MovieLens marker
    "(no genres listed)" is not a genre and is left out (Movie.genre_list()).
    IMAX is a MovieLens value too and is therefore listed; hiding it is a
    presentation choice of the frontend. Counting 5,068 short strings in
    Python is fast and keeps the rule in one place (genre_list).
    """
    counts = Counter(
        genre for genres in db.scalars(select(Movie.genres)) for genre in split_genres(genres)
    )
    return [GenreRead(genre=genre, movie_count=counts[genre]) for genre in sorted(counts)]


def get_featured_movie(db: Session, today: date) -> Movie | None:
    """The catalogue movie featured on Discover for `today` (None if none qualifies).

    Not a ranking: popularity, ratings and recommendations are not used, so
    Discover never repeats the popular list shown on the Recommendations page.
    The rule is a plain daily rotation:
      1. eligible movies are those with complete stored metadata for a hero
         (a poster and an overview) whose TMDB ID was confirmed as `valid` by
         the validation script, so the hero never shows a doubtful poster;
      2. they are ordered by movie_id, and the movie at position
         (day number of `today`) modulo (number of eligible movies) is chosen.
    The same movie is therefore shown all day, and the next day shows the next
    one. `today` is a parameter so tests can use a fixed date.
    """
    eligible_ids = list(
        db.scalars(
            select(MovieMetadata.movie_id)
            .where(
                MovieMetadata.metadata_updated_at.is_not(None),
                MovieMetadata.poster_path.is_not(None),
                MovieMetadata.overview.is_not(None),
                MovieMetadata.tmdb_validation_status == TmdbIdValidationStatus.VALID.value,
            )
            .order_by(MovieMetadata.movie_id)
        )
    )
    if not eligible_ids:
        return None
    chosen_id = eligible_ids[today.toordinal() % len(eligible_ids)]
    return db.get(Movie, chosen_id)


def metadata_status_for(movie: Movie, metadata: MovieMetadata | None) -> MetadataStatus:
    """Describe the locally stored metadata of `movie`."""
    if movie.tmdb_id is None:
        # No title-based guessing is attempted: a wrong match would show
        # another movie's information.
        return MetadataStatus.NO_TMDB_ID
    if metadata is not None and metadata.has_metadata:
        # Earlier metadata is kept (and shown) even if a later refresh failed.
        return MetadataStatus.AVAILABLE
    if metadata is None or metadata.refresh_status is None:
        return MetadataStatus.NOT_IMPORTED
    if metadata.refresh_status == RefreshStatus.NOT_FOUND:
        return MetadataStatus.NOT_FOUND
    # Any other stored outcome is a temporary failure (timeout, 429, ...).
    return MetadataStatus.LOOKUP_FAILED


def get_movie_details(movie: Movie) -> MovieDetailsRead:
    """Combine the local movie with its stored metadata (no TMDB request)."""
    metadata = movie.movie_metadata
    stored = metadata if metadata is not None and metadata.has_metadata else None
    return MovieDetailsRead(
        **MovieRead.from_movie(movie).model_dump(),
        overview=stored.overview if stored else None,
        release_date=stored.release_date if stored else None,
        runtime=stored.runtime if stored else None,
        poster_path=stored.poster_path if stored else None,
        poster_url=build_poster_url(stored.poster_path) if stored else None,
        metadata_status=metadata_status_for(movie, metadata),
        metadata_updated_at=stored.metadata_updated_at if stored else None,
        tmdb_validation_status=(
            metadata.tmdb_validation_status if metadata is not None else "not_checked"
        ),
    )


def get_movies_by_ids(db: Session, movie_ids: Sequence[int]) -> dict[int, Movie]:
    """Load the given catalogue movies (with their metadata) in two queries.

    IDs that are not in the catalogue are simply absent from the result.
    """
    if not movie_ids:
        return {}
    statement = (
        select(Movie)
        .where(Movie.movie_id.in_(set(movie_ids)))
        .options(selectinload(Movie.movie_metadata))
    )
    return {movie.movie_id: movie for movie in db.scalars(statement)}


def build_recommended_movies(
    db: Session, scored_movie_ids: Sequence[tuple[int, float]]
) -> list[RecommendedMovieRead]:
    """Turn a recommender's ranked (movieId, score) list into response objects.

    Preparation for the recommendation phase (no endpoint uses it yet):
    - the recommender's order is kept, and ranks are 1, 2, 3 ...;
    - IDs that are not in the local catalogue are dropped, so the API can
      never return a movie the application does not know;
    - repeated IDs are kept only once (first occurrence).
    """
    movies = get_movies_by_ids(db, [movie_id for movie_id, _ in scored_movie_ids])
    results: list[RecommendedMovieRead] = []
    seen: set[int] = set()
    for movie_id, score in scored_movie_ids:
        movie = movies.get(movie_id)
        if movie is None or movie_id in seen:
            continue
        seen.add(movie_id)
        metadata = movie.movie_metadata
        poster_path = metadata.poster_path if metadata is not None else None
        results.append(
            RecommendedMovieRead(
                **MovieRead.from_movie(movie).model_dump(),
                rank=len(results) + 1,
                score=score,
                poster_url=build_poster_url(poster_path),
            )
        )
    return results
