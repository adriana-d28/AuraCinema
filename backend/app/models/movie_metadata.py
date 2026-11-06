from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.movie import Movie

POSTER_PATH_MAX_LENGTH = 255
VALIDATION_NOTE_MAX_LENGTH = 255

# Value of metadata_source when the metadata came from TMDB (the only source today).
METADATA_SOURCE_TMDB = "tmdb"


class RefreshStatus(StrEnum):
    """Outcome of the last metadata refresh attempt (scripts/refresh_movie_metadata.py).

    The values are the TMDB client's status names, limited to the outcomes
    that are stored. Authentication/configuration problems are never stored:
    they stop the whole run instead.
    """

    OK = "ok"
    NOT_FOUND = "not_found"  # TMDB answered 404 for this TMDB ID.
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"


# Failures worth trying again on the next run, whatever the refresh interval.
TEMPORARY_REFRESH_STATUSES = frozenset(
    {
        RefreshStatus.RATE_LIMITED,
        RefreshStatus.TIMEOUT,
        RefreshStatus.UNAVAILABLE,
        RefreshStatus.INVALID_RESPONSE,
    }
)


class TmdbIdValidationStatus(StrEnum):
    """Result of checking that a movie's TMDB ID points to the right movie
    (scripts/validate_tmdb_ids.py)."""

    NOT_CHECKED = "not_checked"
    VALID = "valid"  # Title and year agree with TMDB.
    NOT_FOUND = "not_found"  # TMDB answered 404: the ID does not exist (any more).
    TITLE_MISMATCH = "title_mismatch"  # TMDB returns a clearly different title.
    YEAR_MISMATCH = "year_mismatch"  # Same title, but the years differ by more than one.
    AMBIGUOUS = "ambiguous"  # Partial agreement only: needs manual review.
    TEMPORARY_ERROR = "temporary_error"  # Timeout, 429, 5xx...: checked again next run.


def _sql_in_list(values: type[StrEnum]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class MovieMetadata(Base):
    """Supplementary information about one catalogue movie, retrieved from TMDB.

    One-to-one with `movies`: movie_id is both the primary key and a foreign
    key, so metadata can only exist for a catalogue movie, and at most once.

    The row holds three independent groups of columns:

    1. The metadata itself (overview ... metadata_updated_at). Written only by
       a successful refresh. MovieLens remains the source of truth for the
       title, genres and IDs, which are therefore not repeated here.
    2. The outcome of the last refresh attempt (refresh_*), so the refresh
       script knows which movies are due, and the API can tell "never
       imported" from "lookup failed".
    3. The TMDB ID validation result (tmdb_validation_*), written only by the
       validation script. ID validation and metadata refresh are different
       operations, so neither group is changed by the other one.

    All columns except the key and the validation status are nullable,
    because TMDB does not always provide every value, and because a row may
    have been created by the validation script before any metadata exists.
    """

    __tablename__ = "movie_metadata"
    __table_args__ = (
        # TMDB uses 0 for "unknown runtime"; that is stored as NULL instead.
        CheckConstraint("runtime > 0", name="runtime_positive"),
        CheckConstraint(
            f"refresh_status IN ({_sql_in_list(RefreshStatus)})", name="refresh_status_valid"
        ),
        CheckConstraint(
            f"tmdb_validation_status IN ({_sql_in_list(TmdbIdValidationStatus)})",
            name="tmdb_validation_status_valid",
        ),
    )

    # CASCADE: this table only holds data derived from TMDB, so it may follow
    # its movie. (Deleting a movie that still has ratings or watchlist entries
    # remains impossible because of the foreign keys of those tables.)
    movie_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("movies.movie_id", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )

    # --- 1. Metadata (from TMDB) ---
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    runtime: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Minutes.
    # Only TMDB's file path ("/abc.jpg"); the image itself is never stored.
    poster_path: Mapped[str | None] = mapped_column(String(POSTER_PATH_MAX_LENGTH), nullable=True)
    metadata_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Time of the last *successful* update; NULL means no metadata yet.
    metadata_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- 2. Last refresh attempt ---
    refresh_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    refresh_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- 3. TMDB ID validation ---
    tmdb_validation_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TmdbIdValidationStatus.NOT_CHECKED.value,
        server_default=TmdbIdValidationStatus.NOT_CHECKED.value,
    )
    tmdb_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tmdb_validation_note: Mapped[str | None] = mapped_column(
        String(VALIDATION_NOTE_MAX_LENGTH), nullable=True
    )
    # HTTP status of the last validation request (e.g. 200, 404, 429).
    tmdb_validation_http_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    movie: Mapped["Movie"] = relationship(back_populates="movie_metadata")

    @property
    def has_metadata(self) -> bool:
        return self.metadata_updated_at is not None

    def __repr__(self) -> str:
        return (
            f"MovieMetadata(movie_id={self.movie_id!r}, "
            f"metadata_updated_at={self.metadata_updated_at!r}, "
            f"tmdb_validation_status={self.tmdb_validation_status!r})"
        )
