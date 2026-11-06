"""Retrieve supplementary movie metadata from TMDB and store it in PostgreSQL.

Usage (from the backend/ folder, virtual environment active):

    python -m scripts.refresh_movie_metadata
    python -m scripts.refresh_movie_metadata --limit 100
    python -m scripts.refresh_movie_metadata --movie-id 1 --movie-id 2571
    python -m scripts.refresh_movie_metadata --refresh-days 7 --batch-size 25

Requires TMDB_API_READ_ACCESS_TOKEN in .env. This script is never run by the
API: user requests only read what it stored in the movie_metadata table.

Which movies are processed (update policy):
- movies without a TMDB ID are skipped and counted separately;
- movies never looked up before are processed (first lookup);
- movies whose last lookup failed temporarily (429, timeout, 5xx, invalid
  answer) are processed again;
- movies looked up less than --refresh-days ago (default
  TMDB_METADATA_REFRESH_DAYS, 30) are skipped; older ones are refreshed;
- --movie-id forces the given movies, whatever their state.

On success the overview, release date, runtime and poster path are written
and metadata_updated_at is set. On failure only refresh_status and
refresh_attempted_at change: metadata stored earlier is kept, never erased.
The TMDB ID validation columns are not touched (see validate_tmdb_ids.py).
"""

import argparse
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, selectinload

from app.models.movie import Movie
from app.models.movie_metadata import (
    METADATA_SOURCE_TMDB,
    POSTER_PATH_MAX_LENGTH,
    TEMPORARY_REFRESH_STATUSES,
    MovieMetadata,
    RefreshStatus,
)
from app.models.utils import utc_now
from app.services.tmdb_service import (
    DEFAULT_MAX_RETRIES,
    FATAL_STATUSES,
    TmdbClient,
    TmdbError,
    TmdbMovieDetails,
    TmdbStatus,
    fetch_movie_details_with_retry,
)
from scripts.tmdb_batch import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_DELAY_SECONDS,
    AbortRun,
    add_common_arguments,
    bounded_int,
    run_in_batches,
)


@dataclass
class RefreshSummary:
    catalogue_movies: int = 0
    selected: int = 0
    skipped_recent: int = 0
    skipped_no_tmdb_id: int = 0
    not_in_catalogue: list[int] = field(default_factory=list)
    refreshed: int = 0
    not_found: int = 0
    failed: Counter = field(default_factory=Counter)  # Temporary failures by status.
    processed: int = 0
    interrupted: bool = False
    aborted_reason: str | None = None

    def lines(self) -> list[str]:
        failed = ", ".join(f"{status}={count}" for status, count in sorted(self.failed.items()))
        lines = [
            "Summary:",
            f"  Movies considered:            {self.catalogue_movies}",
            f"  Selected for lookup:          {self.selected}",
            f"  Skipped (recently updated):   {self.skipped_recent}",
            f"  Skipped (no TMDB ID):         {self.skipped_no_tmdb_id}",
            f"  Processed in this run:        {self.processed}",
            f"  Metadata stored/updated:      {self.refreshed}",
            f"  Not found on TMDB (404):      {self.not_found}",
            f"  Temporary failures:           {sum(self.failed.values())}"
            + (f" ({failed})" if failed else ""),
        ]
        if self.not_in_catalogue:
            lines.append(f"  Requested IDs not in catalogue: {self.not_in_catalogue}")
        if self.interrupted:
            lines.append("  Interrupted: results obtained so far were saved; run again to resume.")
        if self.aborted_reason:
            lines.append(f"  Stopped early: {self.aborted_reason}")
        return lines


def is_refresh_due(metadata: MovieMetadata | None, now: datetime, refresh_days: int) -> bool:
    """Apply the update policy described in the module docstring."""
    if metadata is None or metadata.refresh_attempted_at is None:
        return True  # Never looked up.
    if metadata.refresh_status in TEMPORARY_REFRESH_STATUSES:
        return True  # The last attempt failed for a temporary reason.
    return now - metadata.refresh_attempted_at >= timedelta(days=refresh_days)


def select_movies_to_refresh(
    db: Session,
    summary: RefreshSummary,
    now: datetime,
    refresh_days: int,
    movie_ids: Sequence[int] | None = None,
    limit: int | None = None,
) -> list[Movie]:
    # populate_existing: always use the current database state, even for objects
    # already loaded in this session (sessions do not expire objects on commit).
    statement = (
        select(Movie)
        .options(selectinload(Movie.movie_metadata))
        .order_by(Movie.movie_id)
        .execution_options(populate_existing=True)
    )
    if movie_ids:
        statement = statement.where(Movie.movie_id.in_(set(movie_ids)))
    movies = list(db.scalars(statement))
    summary.catalogue_movies = len(movies)
    if movie_ids:
        found = {movie.movie_id for movie in movies}
        summary.not_in_catalogue = sorted(set(movie_ids) - found)

    due: list[Movie] = []
    for movie in movies:
        if movie.tmdb_id is None:
            summary.skipped_no_tmdb_id += 1
        elif movie_ids or is_refresh_due(movie.movie_metadata, now, refresh_days):
            due.append(movie)
        else:
            summary.skipped_recent += 1
    if limit is not None:
        due = due[:limit]
    summary.selected = len(due)
    return due


def _metadata_row(db: Session, movie: Movie) -> MovieMetadata:
    if movie.movie_metadata is None:
        movie.movie_metadata = MovieMetadata(movie_id=movie.movie_id)
        db.add(movie.movie_metadata)
    return movie.movie_metadata


def store_metadata(
    db: Session, movie: Movie, details: TmdbMovieDetails, now: datetime
) -> MovieMetadata:
    """Write a successful TMDB answer. Values TMDB no longer has become NULL."""
    row = _metadata_row(db, movie)
    row.overview = details.overview
    row.release_date = details.release_date
    row.runtime = details.runtime
    poster = details.poster_path
    row.poster_path = poster if poster is None or len(poster) <= POSTER_PATH_MAX_LENGTH else None
    row.metadata_source = METADATA_SOURCE_TMDB
    row.metadata_updated_at = now
    row.refresh_status = RefreshStatus.OK.value
    row.refresh_attempted_at = now
    return row


def store_failure(db: Session, movie: Movie, status: TmdbStatus, now: datetime) -> MovieMetadata:
    """Record a failed attempt without erasing metadata stored earlier."""
    row = _metadata_row(db, movie)
    row.refresh_status = RefreshStatus(status.value).value
    row.refresh_attempted_at = now
    return row


def refresh_metadata(
    db: Session,
    client: TmdbClient,
    refresh_days: int,
    movie_ids: Sequence[int] | None = None,
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    clock: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> RefreshSummary:
    summary = RefreshSummary()
    movies = select_movies_to_refresh(db, summary, clock(), refresh_days, movie_ids, limit)
    report(
        f"Selected {summary.selected} movie(s) for lookup "
        f"(skipped: {summary.skipped_recent} recently updated, "
        f"{summary.skipped_no_tmdb_id} without TMDB ID)"
    )

    def handle(movie: Movie) -> None:
        assert movie.tmdb_id is not None  # Guaranteed by the selection.
        try:
            details = fetch_movie_details_with_retry(client, movie.tmdb_id, max_retries, sleep)
        except TmdbError as exc:
            if exc.status in FATAL_STATUSES:
                raise AbortRun(
                    f"TMDB rejected the request ({exc.status}); "
                    "check TMDB_API_READ_ACCESS_TOKEN. No further requests were sent."
                ) from None
            store_failure(db, movie, exc.status, clock())
            if exc.status is TmdbStatus.NOT_FOUND:
                summary.not_found += 1
            else:
                summary.failed[exc.status.value] += 1
            return
        store_metadata(db, movie, details, clock())
        summary.refreshed += 1

    state = run_in_batches(db, movies, handle, batch_size, delay_seconds, sleep, report)
    summary.processed = state.processed
    summary.interrupted = state.interrupted
    summary.aborted_reason = state.aborted_reason
    return summary


def main(argv: list[str] | None = None) -> int:
    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.tmdb_service import create_tmdb_client

    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Fetch TMDB metadata for catalogue movies and store it in PostgreSQL."
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--refresh-days",
        type=bounded_int(1, 3650),
        default=settings.tmdb_metadata_refresh_days,
        help="Refresh metadata last looked up at least this many days ago "
        f"(default TMDB_METADATA_REFRESH_DAYS = {settings.tmdb_metadata_refresh_days})",
    )
    args = parser.parse_args(argv)
    # TMDB failures are logged as warnings (TMDB ID and reason; never the token).
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if settings.tmdb_api_read_access_token is None:
        print(
            "ERROR: TMDB_API_READ_ACCESS_TOKEN is not set in .env; no request was sent.",
            file=sys.stderr,
        )
        return 1

    try:
        with create_tmdb_client() as client, get_session_factory()() as db:
            summary = refresh_metadata(
                db,
                client,
                refresh_days=args.refresh_days,
                movie_ids=args.movie_ids,
                limit=args.limit,
                batch_size=args.batch_size,
                delay_seconds=args.delay,
                max_retries=args.max_retries,
            )
    except OperationalError:
        # The driver message can contain the host and user name, so it is not printed.
        print("ERROR: could not connect to the database (is PostgreSQL running?)", file=sys.stderr)
        return 1
    except ProgrammingError:
        print(
            "ERROR: the movie_metadata table does not exist. Run 'alembic upgrade head' first.",
            file=sys.stderr,
        )
        return 1

    print("\n".join(summary.lines()))
    if summary.aborted_reason:
        return 1
    if summary.interrupted:
        return 130  # Conventional exit code after Ctrl+C.
    return 0


if __name__ == "__main__":
    sys.exit(main())
