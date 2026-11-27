"""Import the prepared MovieLens catalogue (movies_catalogue.csv) into PostgreSQL.

Usage (from the backend/ folder, virtual environment active):

    python -m scripts.seed_movies
    python -m scripts.seed_movies --csv path\\to\\movies_catalogue.csv
    python -m scripts.seed_movies --ratings-csv path\\to\\popularity_baseline.csv

The database is the one in DATABASE_URL (.env). The movies table must exist,
so run `alembic upgrade head` (or `alembic upgrade 413ce2f03dd0`) first.

Behaviour:
- The whole file is validated before anything is written. Any invalid row
  stops the import with a message naming the row; nothing is changed.
- New movies are inserted, changed movies are updated, identical movies are
  skipped. Running the script again therefore never creates duplicates.
- Everything happens in one transaction: if an error occurs, no partial
  catalogue is left behind.
- Movies are never deleted, and ratings, watchlists and users are not touched.
- TMDB is never contacted. Supplementary metadata is filled separately by
  scripts/refresh_movie_metadata.py. The only effect on movie_metadata is
  that a row is removed when the movie's TMDB ID changes, because its stored
  metadata and validation result belonged to the old TMDB ID.
- movies.search_title (the normalized title used by search) is recomputed
  for every inserted or updated movie.
- The MovieLens average rating and rating count of every movie are read from
  the popularity baseline output (ml/data/models/popularity_baseline.csv,
  computed from the MovieLens training ratings) and stored in
  movies.movielens_average_rating / movielens_rating_count. That file is
  validated in the same way; a catalogue movie missing from it keeps NULL.
"""

import argparse
import csv
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.titles import build_search_title
from app.models.movie import GENRES_MAX_LENGTH, TITLE_MAX_LENGTH, Movie
from app.models.movie_metadata import MovieMetadata
from app.models.rating import MAX_RATING, MIN_RATING
from app.schemas.common import POSTGRES_INT_MAX

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Output of the ML data-preparation phase (ml/src/prepare_data.py).
DEFAULT_CSV_PATH = BACKEND_DIR.parent / "ml" / "data" / "processed" / "movies_catalogue.csv"

# Output of the popularity baseline (ml/src/popularity_baseline.py): one row
# per catalogue movie with its MovieLens rating count and mean rating.
DEFAULT_RATINGS_CSV_PATH = BACKEND_DIR.parent / "ml" / "data" / "models" / "popularity_baseline.csv"

REQUIRED_COLUMNS = ("movieId", "title", "genres", "imdbId", "tmdbId")
RATINGS_REQUIRED_COLUMNS = ("movieId", "rating_count", "average_rating")


class CatalogueError(Exception):
    """The CSV file is missing or contains invalid data."""


@dataclass(frozen=True)
class MovieRecord:
    """One validated catalogue row."""

    movie_id: int
    title: str
    genres: str
    tmdb_id: int | None
    imdb_id: int | None
    # MovieLens community rating; None when the ratings file has no row for the movie.
    movielens_average_rating: float | None = None
    movielens_rating_count: int | None = None


@dataclass(frozen=True)
class RatingStatistics:
    """MovieLens rating statistics of one movie (one validated ratings-file row)."""

    average_rating: float
    rating_count: int


@dataclass(frozen=True)
class ImportResult:
    inserted: int
    updated: int
    skipped: int  # Already present with identical values.
    # movie_metadata rows removed because the movie's TMDB ID changed.
    metadata_reset: int = 0


def _parse_id(value: str, column: str, row_number: int, required: bool) -> int | None:
    """Parse a positive integer ID. An empty value is allowed only if not required."""
    value = value.strip()
    if value == "":
        if required:
            raise CatalogueError(f"Row {row_number}: {column} is empty")
        return None  # Missing external IDs are kept as NULL, never guessed.
    # Only the characters 0-9 are accepted, so "-1", "1.5", "abc" and "1e3" are rejected.
    if not (value.isascii() and value.isdigit()):
        raise CatalogueError(f"Row {row_number}: {column} {value!r} is not a positive integer")
    number = int(value)
    if not 0 < number <= POSTGRES_INT_MAX:
        raise CatalogueError(f"Row {row_number}: {column} {value!r} is out of range")
    return number


def _parse_text(value: str, column: str, row_number: int, max_length: int) -> str:
    if not value.strip():
        raise CatalogueError(f"Row {row_number}: {column} is empty")
    if len(value) > max_length:
        raise CatalogueError(f"Row {row_number}: {column} is longer than {max_length} characters")
    return value  # Kept exactly as in MovieLens.


def load_catalogue(csv_path: Path) -> list[MovieRecord]:
    """Read and validate the whole catalogue file. Raises CatalogueError."""
    if not csv_path.is_file():
        raise CatalogueError(f"Catalogue file not found: {csv_path}")

    # utf-8-sig also accepts a file saved with a byte-order mark (e.g. by Excel).
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CatalogueError(f"Missing required column(s): {', '.join(missing)}")

        records: list[MovieRecord] = []
        seen_ids: set[int] = set()
        # Row 1 is the header, so the first data row is row 2 (as in a spreadsheet).
        for row_number, row in enumerate(reader, start=2):
            if None in row.values():
                raise CatalogueError(f"Row {row_number}: too few columns")
            movie_id = _parse_id(row["movieId"], "movieId", row_number, required=True)
            if movie_id in seen_ids:
                raise CatalogueError(f"Row {row_number}: duplicate movieId {movie_id}")
            seen_ids.add(movie_id)
            records.append(
                MovieRecord(
                    movie_id=movie_id,
                    title=_parse_text(row["title"], "title", row_number, TITLE_MAX_LENGTH),
                    genres=_parse_text(row["genres"], "genres", row_number, GENRES_MAX_LENGTH),
                    tmdb_id=_parse_id(row["tmdbId"], "tmdbId", row_number, required=False),
                    imdb_id=_parse_id(row["imdbId"], "imdbId", row_number, required=False),
                )
            )

    if not records:
        raise CatalogueError("The catalogue file contains no movies")
    return records


def _parse_average_rating(value: str, row_number: int) -> float:
    value = value.strip()
    try:
        number = float(value)
    except ValueError:
        raise CatalogueError(
            f"Ratings file row {row_number}: average_rating {value!r} is not a number"
        ) from None
    if not (math.isfinite(number) and MIN_RATING <= number <= MAX_RATING):
        raise CatalogueError(
            f"Ratings file row {row_number}: average_rating {value!r} is outside "
            f"{MIN_RATING}-{MAX_RATING}"
        )
    return number


def load_rating_statistics(csv_path: Path) -> dict[int, RatingStatistics]:
    """Read and validate the MovieLens rating statistics file. Raises CatalogueError."""
    if not csv_path.is_file():
        raise CatalogueError(f"Ratings file not found: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = [c for c in RATINGS_REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CatalogueError(f"Ratings file: missing required column(s): {', '.join(missing)}")

        statistics: dict[int, RatingStatistics] = {}
        for row_number, row in enumerate(reader, start=2):
            if None in row.values():
                raise CatalogueError(f"Ratings file row {row_number}: too few columns")
            movie_id = _parse_id(row["movieId"], "movieId", row_number, required=True)
            if movie_id in statistics:
                raise CatalogueError(f"Ratings file row {row_number}: duplicate movieId {movie_id}")
            statistics[movie_id] = RatingStatistics(
                average_rating=_parse_average_rating(row["average_rating"], row_number),
                rating_count=_parse_id(
                    row["rating_count"], "rating_count", row_number, required=True
                ),
            )

    if not statistics:
        raise CatalogueError("The ratings file contains no movies")
    return statistics


def add_rating_statistics(
    records: list[MovieRecord], statistics: dict[int, RatingStatistics]
) -> list[MovieRecord]:
    """Return the records with their MovieLens rating statistics filled in.

    A movie without a row in `statistics` keeps None; rows for movies that are
    not in the catalogue are ignored.
    """
    result = []
    for record in records:
        stats = statistics.get(record.movie_id)
        result.append(
            replace(
                record,
                movielens_average_rating=stats.average_rating if stats else None,
                movielens_rating_count=stats.rating_count if stats else None,
            )
        )
    return result


def import_movies(db: Session, records: list[MovieRecord]) -> ImportResult:
    """Insert or update the given movies in a single transaction."""
    inserted = updated = skipped = metadata_reset = 0
    try:
        # About 5,000 rows: loading the existing catalogue once is simpler and
        # faster than one SELECT per movie.
        existing = {movie.movie_id: movie for movie in db.scalars(select(Movie))}
        changed_tmdb_ids: list[int] = []
        for record in records:
            movie = existing.get(record.movie_id)
            if movie is None:
                # search_title is derived from the title by the Movie model.
                db.add(
                    Movie(
                        movie_id=record.movie_id,
                        title=record.title,
                        genres=record.genres,
                        tmdb_id=record.tmdb_id,
                        imdb_id=record.imdb_id,
                        movielens_average_rating=record.movielens_average_rating,
                        movielens_rating_count=record.movielens_rating_count,
                    )
                )
                inserted += 1
            elif (
                movie.title,
                movie.genres,
                movie.tmdb_id,
                movie.imdb_id,
                movie.search_title,
                movie.movielens_average_rating,
                movie.movielens_rating_count,
            ) == (
                record.title,
                record.genres,
                record.tmdb_id,
                record.imdb_id,
                build_search_title(record.title),
                record.movielens_average_rating,
                record.movielens_rating_count,
            ):
                skipped += 1
            else:
                if movie.tmdb_id != record.tmdb_id:
                    changed_tmdb_ids.append(movie.movie_id)
                movie.title = record.title  # Also recomputes search_title.
                movie.genres = record.genres
                movie.tmdb_id = record.tmdb_id
                movie.imdb_id = record.imdb_id
                movie.movielens_average_rating = record.movielens_average_rating
                movie.movielens_rating_count = record.movielens_rating_count
                updated += 1
        if changed_tmdb_ids:
            # Metadata and validation results stored for the old TMDB ID would
            # describe a different TMDB entry, so they are discarded and will be
            # fetched again by the refresh and validation scripts.
            result = db.execute(
                delete(MovieMetadata).where(MovieMetadata.movie_id.in_(changed_tmdb_ids))
            )
            metadata_reset = result.rowcount or 0
        db.commit()
    except Exception:
        db.rollback()  # Leave the catalogue exactly as it was before the import.
        raise
    return ImportResult(
        inserted=inserted, updated=updated, skipped=skipped, metadata_reset=metadata_reset
    )


def count_movies(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Movie)) or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import movies_catalogue.csv into PostgreSQL.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV_PATH,
        help=f"Path to movies_catalogue.csv (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--ratings-csv",
        type=Path,
        default=DEFAULT_RATINGS_CSV_PATH,
        help="Path to the MovieLens rating statistics, popularity_baseline.csv "
        f"(default: {DEFAULT_RATINGS_CSV_PATH})",
    )
    args = parser.parse_args(argv)

    try:
        records = load_catalogue(args.csv)
        records = add_rating_statistics(records, load_rating_statistics(args.ratings_csv))
    except CatalogueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {len(records)} movies from {args.csv}")
    with_rating = sum(1 for record in records if record.movielens_rating_count is not None)
    print(f"MovieLens rating statistics found for {with_rating} of them ({args.ratings_csv})")

    # Imported here so that validating a file does not require database settings.
    from app.db.session import get_session_factory

    try:
        with get_session_factory()() as db:
            result = import_movies(db, records)
            total = count_movies(db)
    except OperationalError:
        # The driver message can contain the host and user name, so it is not printed.
        print("ERROR: could not connect to the database (is PostgreSQL running?)", file=sys.stderr)
        return 1
    except ProgrammingError:
        print(
            "ERROR: the database schema is missing or outdated (movies/movie_metadata). "
            "Run 'alembic upgrade head' first.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Inserted: {result.inserted}  Updated: {result.updated}  "
        f"Skipped (unchanged): {result.skipped}"
    )
    if result.metadata_reset:
        print(f"Stored TMDB metadata removed because the TMDB ID changed: {result.metadata_reset}")
    print(f"Movies now in the database: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
