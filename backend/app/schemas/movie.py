from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

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
    """Core catalogue data, taken only from the local MovieLens catalogue."""

    movie_id: int = Field(description="MovieLens movieId (the AuraCinema movie identifier)")
    title: str = Field(description="Original MovieLens title, including the year")
    genres: list[str] = Field(description="MovieLens genres; empty if none are listed")
    tmdb_id: int | None = Field(description="The Movie Database ID, if known")
    imdb_id: int | None = Field(description="Numeric IMDb ID (e.g. 114709 = tt0114709)")

    @classmethod
    def from_movie(cls, movie: Movie) -> "MovieRead":
        return cls(
            movie_id=movie.movie_id,
            title=movie.title,
            genres=movie.genre_list(),
            tmdb_id=movie.tmdb_id,
            imdb_id=movie.imdb_id,
        )


class MovieListResponse(BaseModel):
    """One page of catalogue results plus the information needed to paginate."""

    items: list[MovieRead]
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
    poster_url: str | None = Field(description="Poster URL from the stored metadata, if any")
