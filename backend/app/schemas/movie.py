from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.core.titles import parse_movielens_title
from app.models.movie import Movie


class MetadataStatus(StrEnum):
    """Why the supplementary metadata fields are (or are not) filled in.

    The metadata is read from the local movie_metadata table, never from a
    live TMDB request, so the status describes what is stored locally.
    """

    AVAILABLE = "available"  # Metadata was imported from TMDB.
    NO_TMDB_ID = "no_tmdb_id"  # The movie has no TMDB ID in the catalogue.
    NOT_IMPORTED = "not_imported"  # The refresh script has not processed this movie yet.
    NOT_FOUND = "not_found"  # The last TMDB lookup answered 404 for this TMDB ID.
    LOOKUP_FAILED = "lookup_failed"  # The last lookup failed temporarily (timeout, 429...).


class MovieRead(BaseModel):
    """Core catalogue data, taken only from the local MovieLens catalogue
    (including the MovieLens average rating)."""

    movie_id: int = Field(description="MovieLens movieId (the AuraCinema movie identifier)")
    title: str = Field(description="Original MovieLens title, including the year")
    # The two display fields below are derived from `title` by the same rules
    # the search and the TMDB ID check use (app/core/titles.py), so every
    # client shows "The Matrix" + 1999 instead of "Matrix, The (1999)" without
    # repeating those rules itself. `title` itself is never changed.
    display_title: str = Field(
        description="Readable main title: trailing article moved back, year and "
        "alternative titles removed (e.g. 'The Matrix')"
    )
    year: int | None = Field(description="Year taken from the MovieLens title, if present")
    genres: list[str] = Field(description="MovieLens genres; empty if none are listed")
    tmdb_id: int | None = Field(description="The Movie Database ID, if known")
    imdb_id: int | None = Field(description="Numeric IMDb ID (e.g. 114709 = tt0114709)")
    # MovieLens community rating (not AuraCinema users' ratings). Both are null
    # until scripts/seed_movies.py has imported them.
    movielens_average_rating: float | None = Field(
        description="Mean MovieLens rating of the movie (0.5-5.0), 2 decimals"
    )
    movielens_rating_count: int | None = Field(
        description="Number of MovieLens ratings behind movielens_average_rating"
    )

    @classmethod
    def from_movie(cls, movie: Movie) -> "MovieRead":
        parsed = parse_movielens_title(movie.title)
        return cls(
            movie_id=movie.movie_id,
            title=movie.title,
            display_title=parsed.main,
            year=parsed.year,
            genres=movie.genre_list(),
            tmdb_id=movie.tmdb_id,
            imdb_id=movie.imdb_id,
            movielens_average_rating=(
                round(movie.movielens_average_rating, 2)
                if movie.movielens_average_rating is not None
                else None
            ),
            movielens_rating_count=movie.movielens_rating_count,
        )


class MovieSummaryRead(MovieRead):
    """A movie as shown in lists (catalogue pages, watchlist, ratings).

    It adds only the poster to the catalogue data, so a list can be drawn
    without one /details request per movie. The poster comes from the locally
    stored metadata; null means: show a placeholder.
    """

    poster_url: str | None = Field(description="Poster URL from the stored metadata, if any")


class MovieListResponse(BaseModel):
    """One page of catalogue results plus the information needed to paginate."""

    items: list[MovieSummaryRead]
    total: int = Field(description="Number of movies matching the search (all pages)")
    limit: int
    offset: int


class MovieDetailsRead(MovieRead):
    """Local catalogue data plus the supplementary metadata stored locally.

    The metadata fields are null whenever no metadata is stored;
    metadata_status explains why. Title and genres always remain the
    MovieLens values. No field is ever filled with invented data.
    """

    model_config = ConfigDict(use_enum_values=True)

    overview: str | None = Field(description="Plot summary (from TMDB)")
    release_date: date | None = Field(description="Release date (from TMDB)")
    runtime: int | None = Field(description="Runtime in minutes (from TMDB)")
    poster_path: str | None = Field(description="TMDB poster file path")
    poster_url: str | None = Field(
        description="Full poster image URL (w500 size); null means: show a placeholder"
    )
    metadata_status: MetadataStatus
    metadata_updated_at: datetime | None = Field(
        description="When the metadata was last imported successfully"
    )
    tmdb_validation_status: str = Field(
        description="Result of the TMDB ID check (e.g. valid, ambiguous, not_checked)"
    )


class RecommendedMovieRead(MovieRead):
    """One recommendation result, prepared for the future recommendation endpoint.

    The recommender returns MovieLens movieIds and scores; the backend turns
    them into these objects, keeping the recommender's order. Internal model
    indices (item_index) are never part of the response.
    """

    rank: int = Field(ge=1, description="1 = best recommendation")
    score: float = Field(description="Score given by the recommendation model")
    # Declared here (instead of inheriting MovieSummaryRead) so the field order
    # and contract of the Phase 6 recommendation response stay as documented.
    poster_url: str | None = Field(description="Poster URL from the stored metadata, if any")


class GenreRead(BaseModel):
    """One genre of the catalogue and how many catalogue movies have it."""

    genre: str = Field(description="MovieLens genre name, e.g. 'Sci-Fi'")
    movie_count: int = Field(ge=1, description="Number of catalogue movies with this genre")
