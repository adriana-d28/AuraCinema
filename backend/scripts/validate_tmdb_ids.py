"""Check that each movie's TMDB ID really points to the expected movie.

Usage (from the backend/ folder, virtual environment active):

    python -m scripts.validate_tmdb_ids
    python -m scripts.validate_tmdb_ids --limit 200
    python -m scripts.validate_tmdb_ids --movie-id 2571          # revalidate one movie
    python -m scripts.validate_tmdb_ids --recheck ambiguous      # revalidate a group

Requires TMDB_API_READ_ACCESS_TOKEN in .env. Never run by the API.

This is different from refreshing metadata: it checks the *identifier*, not
the content. An HTTP 200 answer alone is not accepted as proof. The TMDB
title and release year are compared with the MovieLens title and year:

| Title comparison                     | Years (+/- 1 allowed) | Result          |
|--------------------------------------|-----------------------|-----------------|
| similar (>= 0.85) or identical       | agree or unknown      | valid           |
| similar                              | differ                | year_mismatch   |
| partial (one contains the other,     | agree or unknown      | ambiguous       |
|   or similarity >= 0.6)              | differ                | title_mismatch  |
| different (< 0.6)                    | any                   | title_mismatch  |
| TMDB answers 404                     |                       | not_found       |
| 429 / timeout / 5xx / invalid answer |                       | temporary_error |

Titles are compared after normalization (case, accents, punctuation), with
MovieLens trailing articles moved back ("Matrix, The" -> "The Matrix") and
with alternative titles in parentheses also tried, against both TMDB's
`title` and `original_title`. Similarity is difflib's ratio (standard library).
IDs are never replaced automatically: doubtful cases are only marked for
manual review, with a note explaining the decision.

Incremental behaviour: only movies never checked (including movies added to
the catalogue later, or whose TMDB ID changed, because the import script
then resets their row) and movies with a temporary_error are processed.
Final results (valid, not_found, title_mismatch, year_mismatch, ambiguous)
are not requested again unless --movie-id or --recheck asks for it. Results
are saved after every batch, so an interrupted run resumes where it stopped.
"""

import argparse
import logging
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session, selectinload

from app.core.titles import normalize_text, parse_movielens_title
from app.models.movie import Movie
from app.models.movie_metadata import (
    VALIDATION_NOTE_MAX_LENGTH,
    MovieMetadata,
    TmdbIdValidationStatus,
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
    run_in_batches,
)

SIMILAR_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.6
YEAR_TOLERANCE = 1  # Festival vs. general release dates often differ by a year.
# A contained title must be at least this long to count ("it" inside "edit" does not).
MIN_CONTAINED_LENGTH = 4

# Results that need no new request unless explicitly asked for.
FINAL_STATUSES = frozenset(
    {
        TmdbIdValidationStatus.VALID,
        TmdbIdValidationStatus.NOT_FOUND,
        TmdbIdValidationStatus.TITLE_MISMATCH,
        TmdbIdValidationStatus.YEAR_MISMATCH,
        TmdbIdValidationStatus.AMBIGUOUS,
    }
)
# Only English leading articles are dropped for comparison ("The Matrix" ~ "Matrix").
# Words such as "Die" or "La" are not, because they also start ordinary titles
# ("Die Hard"), and dropping them could create false matches.
_LEADING_ARTICLES = frozenset({"the", "a", "an"})


# --- Title and year comparison (no database or network) ----------------------


@dataclass(frozen=True)
class ValidationOutcome:
    status: TmdbIdValidationStatus
    note: str


def _comparable_forms(titles: Iterable[str | None]) -> set[str]:
    """Normalized titles, each also without a leading article."""
    forms: set[str] = set()
    for title in titles:
        if not title:
            continue
        normalized = normalize_text(title)
        if not normalized:
            continue
        forms.add(normalized)
        first, _, rest = normalized.partition(" ")
        if rest and first in _LEADING_ARTICLES:
            forms.add(rest)
    return forms


def _contains(short: str, long: str) -> bool:
    """True when `short` appears in `long` as whole words."""
    return len(short) >= MIN_CONTAINED_LENGTH and f" {short} " in f" {long} "


def compare_titles(
    movielens_titles: Iterable[str], tmdb_titles: Iterable[str | None]
) -> tuple[float, bool]:
    """Return (best similarity ratio 0-1, whether one title contains the other)."""
    best, contained = 0.0, False
    tmdb_forms = _comparable_forms(tmdb_titles)
    for ml in _comparable_forms(movielens_titles):
        for tmdb in tmdb_forms:
            if ml == tmdb:
                return 1.0, True
            best = max(best, SequenceMatcher(None, ml, tmdb).ratio())
            contained = contained or _contains(ml, tmdb) or _contains(tmdb, ml)
    return best, contained


def compare_with_tmdb(movielens_title: str, details: TmdbMovieDetails) -> ValidationOutcome:
    """Decide whether the TMDB answer describes the MovieLens movie (see table above)."""
    if details.title is None and details.original_title is None:
        return ValidationOutcome(TmdbIdValidationStatus.AMBIGUOUS, "TMDB returned no title")

    parsed = parse_movielens_title(movielens_title)
    similarity, contained = compare_titles(
        parsed.all_titles, (details.title, details.original_title)
    )
    ml_year = parsed.year
    tmdb_year = details.release_date.year if details.release_date else None
    year_difference = abs(ml_year - tmdb_year) if ml_year and tmdb_year else None
    years_differ = year_difference is not None and year_difference > YEAR_TOLERANCE

    tmdb_label = f"TMDB '{details.title or details.original_title}' ({tmdb_year or 'no year'})"
    years = f"MovieLens {ml_year or 'no year'}, TMDB {tmdb_year or 'no year'}"
    score = f"similarity {similarity:.2f}"

    if similarity >= SIMILAR_THRESHOLD:
        if years_differ:
            return ValidationOutcome(
                TmdbIdValidationStatus.YEAR_MISMATCH, f"Title matches but years differ ({years})"
            )
        if year_difference is None:
            return ValidationOutcome(
                TmdbIdValidationStatus.VALID, f"Title matches; year not compared ({years})"
            )
        return ValidationOutcome(TmdbIdValidationStatus.VALID, f"Title and year match ({score})")

    if contained or similarity >= PARTIAL_THRESHOLD:
        if years_differ:
            return ValidationOutcome(
                TmdbIdValidationStatus.TITLE_MISMATCH,
                f"Title only partially matches {tmdb_label} and years differ ({score})",
            )
        return ValidationOutcome(
            TmdbIdValidationStatus.AMBIGUOUS,
            f"Title only partially matches {tmdb_label} ({score}); manual review needed",
        )

    return ValidationOutcome(
        TmdbIdValidationStatus.TITLE_MISMATCH, f"Title differs from {tmdb_label} ({score})"
    )


# --- Selection and persistence ------------------------------------------------


@dataclass
class ValidationSummary:
    catalogue_movies: int = 0
    selected: int = 0
    skipped_already_validated: int = 0
    skipped_no_tmdb_id: int = 0
    not_in_catalogue: list[int] = field(default_factory=list)
    results: Counter = field(default_factory=Counter)  # Stored status -> count.
    processed: int = 0
    interrupted: bool = False
    aborted_reason: str | None = None

    def lines(self) -> list[str]:
        lines = [
            "Summary:",
            f"  Movies considered:              {self.catalogue_movies}",
            f"  Selected for validation:        {self.selected}",
            f"  Skipped (already validated):    {self.skipped_already_validated}",
            f"  Skipped (no TMDB ID):           {self.skipped_no_tmdb_id}",
            f"  Processed in this run:          {self.processed}",
        ]
        for status in TmdbIdValidationStatus:
            if self.results[status.value]:
                lines.append(f"  {status.value + ':':<32}{self.results[status.value]}")
        if self.not_in_catalogue:
            lines.append(f"  Requested IDs not in catalogue: {self.not_in_catalogue}")
        if self.interrupted:
            lines.append("  Interrupted: results obtained so far were saved; run again to resume.")
        if self.aborted_reason:
            lines.append(f"  Stopped early: {self.aborted_reason}")
        return lines


def is_validation_due(
    metadata: MovieMetadata | None, recheck: frozenset[str] = frozenset()
) -> bool:
    if metadata is None:
        return True  # Never checked (e.g. a movie added to the catalogue later).
    status = metadata.tmdb_validation_status
    if status in recheck:
        return True
    return status not in FINAL_STATUSES  # not_checked or temporary_error.


def select_movies_to_validate(
    db: Session,
    summary: ValidationSummary,
    movie_ids: Sequence[int] | None = None,
    recheck: Iterable[str] = (),
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

    recheck_set = frozenset(recheck)
    due: list[Movie] = []
    for movie in movies:
        if movie.tmdb_id is None:
            summary.skipped_no_tmdb_id += 1
        elif movie_ids or is_validation_due(movie.movie_metadata, recheck_set):
            due.append(movie)
        else:
            summary.skipped_already_validated += 1
    if limit is not None:
        due = due[:limit]
    summary.selected = len(due)
    return due


def store_validation(
    db: Session,
    movie: Movie,
    status: TmdbIdValidationStatus,
    note: str,
    http_status: int | None,
    now: datetime,
) -> MovieMetadata:
    """Write only the validation columns; metadata columns are left as they are."""
    if movie.movie_metadata is None:
        movie.movie_metadata = MovieMetadata(movie_id=movie.movie_id)
        db.add(movie.movie_metadata)
    row = movie.movie_metadata
    row.tmdb_validation_status = status.value
    row.tmdb_validation_note = note[:VALIDATION_NOTE_MAX_LENGTH]
    row.tmdb_validation_http_status = http_status
    row.tmdb_validated_at = now
    return row


def validate_tmdb_ids(
    db: Session,
    client: TmdbClient,
    movie_ids: Sequence[int] | None = None,
    recheck: Iterable[str] = (),
    limit: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    clock: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> ValidationSummary:
    summary = ValidationSummary()
    movies = select_movies_to_validate(db, summary, movie_ids, recheck, limit)
    report(
        f"Selected {summary.selected} movie(s) for validation "
        f"(skipped: {summary.skipped_already_validated} already validated, "
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
            if exc.status is TmdbStatus.NOT_FOUND:
                status, note = TmdbIdValidationStatus.NOT_FOUND, "TMDB answered 404 for this ID"
            else:
                status = TmdbIdValidationStatus.TEMPORARY_ERROR
                note = f"Temporary TMDB problem ({exc.status}); will be checked again"
            store_validation(db, movie, status, note, exc.http_status, clock())
            summary.results[status.value] += 1
            return
        outcome = compare_with_tmdb(movie.title, details)
        store_validation(db, movie, outcome.status, outcome.note, 200, clock())
        summary.results[outcome.status.value] += 1

    state = run_in_batches(db, movies, handle, batch_size, delay_seconds, sleep, report)
    summary.processed = state.processed
    summary.interrupted = state.interrupted
    summary.aborted_reason = state.aborted_reason
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the TMDB IDs of catalogue movies (title and year comparison)."
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--recheck",
        action="append",
        default=[],
        choices=sorted(status.value for status in FINAL_STATUSES),
        help="Also revalidate movies that currently have this result (repeatable)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from app.core.config import get_settings
    from app.db.session import get_session_factory
    from app.services.tmdb_service import create_tmdb_client

    if get_settings().tmdb_api_read_access_token is None:
        print(
            "ERROR: TMDB_API_READ_ACCESS_TOKEN is not set in .env; no request was sent.",
            file=sys.stderr,
        )
        return 1

    try:
        with create_tmdb_client() as client, get_session_factory()() as db:
            summary = validate_tmdb_ids(
                db,
                client,
                movie_ids=args.movie_ids,
                recheck=args.recheck,
                limit=args.limit,
                batch_size=args.batch_size,
                delay_seconds=args.delay,
                max_retries=args.max_retries,
            )
    except OperationalError:
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
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
