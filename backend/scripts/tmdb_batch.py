"""Shared helpers for the TMDB maintenance scripts.

Both scripts (refresh_movie_metadata and validate_tmdb_ids) process a list
of movies with the same safety rules:

- requests are sent one at a time (no concurrency), with a short pause
  between them, well below TMDB's rate limit;
- work is committed after every batch, so an interruption (Ctrl+C) or a
  crash loses at most the batch in progress; on Ctrl+C the results already
  obtained in that batch are committed too;
- a failure that affects every request (e.g. the token is rejected) stops the
  run instead of repeating the same error thousands of times;
- the scripts only select movies that still need work, so running them again
  simply resumes where the previous run stopped.
"""

import argparse
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.tmdb_service import DEFAULT_MAX_RETRIES

DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 500
# 0.1 s between requests means at most about 10 requests per second, far below
# the limit documented by TMDB, while a full catalogue run stays reasonably short.
DEFAULT_DELAY_SECONDS = 0.1
MAX_DELAY_SECONDS = 10.0
MAX_RETRIES_LIMIT = 5


class AbortRun(Exception):
    """Raised by a handler to stop the whole run (e.g. TMDB rejected the token)."""


@dataclass
class RunState:
    processed: int = 0
    interrupted: bool = False
    aborted_reason: str | None = None


def run_in_batches[T](
    db: Session,
    items: Sequence[T],
    handle: Callable[[T], None],
    batch_size: int,
    delay_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> RunState:
    """Call `handle(item)` for every item, committing after each batch.

    `handle` changes ORM objects in `db` but does not commit. It may raise
    AbortRun to stop the run; the work already done is still committed.
    """
    state = RunState()
    total_batches = math.ceil(len(items) / batch_size) if items else 0
    for batch_number, start in enumerate(range(0, len(items), batch_size), start=1):
        try:
            for item in items[start : start + batch_size]:
                if state.processed and delay_seconds:
                    sleep(delay_seconds)  # Pause between consecutive TMDB requests.
                handle(item)
                state.processed += 1
        except AbortRun as exc:
            state.aborted_reason = str(exc)
        except KeyboardInterrupt:
            state.interrupted = True
        db.commit()  # Keep everything obtained so far, even when stopping early.
        report(f"Batch {batch_number}/{total_batches}: {state.processed}/{len(items)} processed")
        if state.aborted_reason is not None or state.interrupted:
            break
    return state


def bounded_int(low: int, high: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number

    return parse


def bounded_float(low: float, high: float) -> Callable[[str], float]:
    def parse(value: str) -> float:
        number = float(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be between {low} and {high}")
        return number

    return parse


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Command-line options shared by both scripts."""
    parser.add_argument(
        "--batch-size",
        type=bounded_int(1, MAX_BATCH_SIZE),
        default=DEFAULT_BATCH_SIZE,
        help=f"Movies per batch; results are saved after each batch (default {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--limit",
        type=bounded_int(1, 1_000_000),
        default=None,
        help="Process at most this many movies in this run (default: all that need it)",
    )
    parser.add_argument(
        "--movie-id",
        dest="movie_ids",
        type=bounded_int(1, 2_147_483_647),
        action="append",
        default=None,
        help="Process only this MovieLens movieId, even if it is up to date (repeatable)",
    )
    parser.add_argument(
        "--delay",
        type=bounded_float(0.0, MAX_DELAY_SECONDS),
        default=DEFAULT_DELAY_SECONDS,
        help=f"Seconds to wait between TMDB requests (default {DEFAULT_DELAY_SECONDS})",
    )
    parser.add_argument(
        "--max-retries",
        type=bounded_int(0, MAX_RETRIES_LIMIT),
        default=DEFAULT_MAX_RETRIES,
        help=f"Retries after 429/timeout/5xx for one movie (default {DEFAULT_MAX_RETRIES})",
    )
