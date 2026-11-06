"""Small client for The Movie Database (TMDB) API.

Only one TMDB operation is needed: "movie details"
(GET https://api.themoviedb.org/3/movie/{tmdb_id}). The client:

- authenticates with the TMDB "API Read Access Token" as a Bearer header, so
  the credential never appears in URLs (and therefore never in access logs);
- applies a timeout to every request;
- turns every failure into a TmdbError with a clear TmdbStatus, instead of
  returning empty data that would look like a successful answer;
- keeps only the few fields AuraCinema uses, not the raw TMDB response.

Since the metadata refinements, the client is used only by the maintenance
scripts (scripts/refresh_movie_metadata.py and scripts/validate_tmdb_ids.py).
Normal API requests read the metadata stored in PostgreSQL and never call TMDB,
so the in-memory cache of the previous version is no longer needed.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

import httpx2

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TMDB_API_BASE_URL = "https://api.themoviedb.org/3"
# Image URLs are built from three parts: base URL + size + file path. The base
# URL and the size below are values documented by TMDB's /configuration
# endpoint ("secure_base_url" and one of the "poster_sizes").
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/"
POSTER_SIZE = "w500"

# Retry policy used by fetch_movie_details_with_retry.
DEFAULT_MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0
# Upper bound for any single wait, including a server-provided Retry-After,
# so a misbehaving header can never pause a script for hours.
MAX_RETRY_DELAY_SECONDS = 30.0


class TmdbStatus(StrEnum):
    """Outcome of one TMDB request."""

    OK = "ok"
    NOT_CONFIGURED = "not_configured"  # No TMDB access token is configured.
    NOT_FOUND = "not_found"  # TMDB answered 404 for this TMDB ID.
    AUTH_FAILED = "auth_failed"  # TMDB rejected the access token (401/403).
    RATE_LIMITED = "rate_limited"  # TMDB answered 429 (too many requests).
    TIMEOUT = "timeout"  # TMDB did not answer within the configured timeout.
    UNAVAILABLE = "unavailable"  # Connection failure or another HTTP error.
    INVALID_RESPONSE = "invalid_response"  # TMDB answered with unexpected content.


# Failures that may succeed if the same request is repeated a little later.
RETRYABLE_STATUSES = frozenset(
    {TmdbStatus.RATE_LIMITED, TmdbStatus.TIMEOUT, TmdbStatus.UNAVAILABLE}
)
# Failures that affect every request, so a batch run must stop instead of
# repeating the same error thousands of times.
FATAL_STATUSES = frozenset({TmdbStatus.AUTH_FAILED, TmdbStatus.NOT_CONFIGURED})


class TmdbError(Exception):
    """A TMDB lookup failed. `status` says why.

    `http_status` is the HTTP status code when TMDB answered (None for
    timeouts and connection errors). `retry_after` is the number of seconds
    from TMDB's Retry-After header, when a 429 answer included one.
    """

    def __init__(
        self,
        status: TmdbStatus,
        message: str,
        http_status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.http_status = http_status
        self.retry_after = retry_after


@dataclass(frozen=True)
class TmdbMovieDetails:
    """The subset of TMDB's movie-details response used by AuraCinema.

    `title` and `original_title` are used only to validate that the TMDB ID
    belongs to the expected movie; they are never stored or shown, because the
    MovieLens title remains the source of truth.
    """

    overview: str | None
    release_date: date | None
    runtime: int | None
    poster_path: str | None
    title: str | None = None
    original_title: str | None = None

    @property
    def poster_url(self) -> str | None:
        return build_poster_url(self.poster_path)


def build_poster_url(poster_path: str | None) -> str | None:
    """Full image URL for a TMDB poster path, or None when there is no poster."""
    if poster_path is None:
        return None
    return f"{TMDB_IMAGE_BASE_URL}{POSTER_SIZE}{poster_path}"


def _optional_text(value: Any) -> str | None:
    """TMDB uses "" (or null) for unknown text fields; return None for those."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_date(value: Any) -> date | None:
    """Parse "YYYY-MM-DD"; TMDB sends "" when the release date is unknown."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _optional_positive_int(value: Any) -> int | None:
    """TMDB uses 0 (or null) when the runtime is unknown."""
    # bool is a subclass of int in Python, so it is excluded explicitly.
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _optional_image_path(value: Any) -> str | None:
    """Accept only paths of the documented form "/abc123.jpg"."""
    if isinstance(value, str) and value.startswith("/") and len(value) > 1:
        return value
    return None


def parse_movie_details(data: dict[str, Any]) -> TmdbMovieDetails:
    """Map TMDB's JSON object to TmdbMovieDetails. Missing fields become None."""
    return TmdbMovieDetails(
        overview=_optional_text(data.get("overview")),
        release_date=_optional_date(data.get("release_date")),
        runtime=_optional_positive_int(data.get("runtime")),
        poster_path=_optional_image_path(data.get("poster_path")),
        title=_optional_text(data.get("title")),
        original_title=_optional_text(data.get("original_title")),
    )


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header ("5"); None if absent or not a number.

    The HTTP-date form of the header is not used by TMDB and is ignored.
    """
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    if seconds < 0 or seconds != seconds:  # Negative or NaN.
        return None
    return seconds


class TmdbClient:
    """Fetches movie details from TMDB. Use it as a context manager or call close()."""

    def __init__(
        self,
        access_token: str | None,
        timeout_seconds: float,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        """`transport` lets tests replace the network with httpx2.MockTransport."""
        self._configured = access_token is not None
        headers = {"Accept": "application/json"}
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
        self._http = httpx2.Client(
            base_url=TMDB_API_BASE_URL,
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    @property
    def is_configured(self) -> bool:
        return self._configured

    def get_movie_details(self, tmdb_id: int) -> TmdbMovieDetails:
        """Return TMDB details for `tmdb_id`, or raise TmdbError (one request, no retry)."""
        if not self._configured:
            raise TmdbError(TmdbStatus.NOT_CONFIGURED, "TMDB access token is not configured")

        try:
            response = self._http.get(f"/movie/{tmdb_id}")
        except httpx2.TimeoutException:
            raise self._failure(tmdb_id, TmdbStatus.TIMEOUT, "request timed out") from None
        except httpx2.RequestError as exc:
            # Only the exception type is logged; messages could contain URLs.
            reason = f"connection error ({type(exc).__name__})"
            raise self._failure(tmdb_id, TmdbStatus.UNAVAILABLE, reason) from None

        code = response.status_code
        if code in (401, 403):
            raise self._failure(
                tmdb_id, TmdbStatus.AUTH_FAILED, f"HTTP {code}: check the token", code
            )
        if code == 404:
            raise self._failure(tmdb_id, TmdbStatus.NOT_FOUND, "HTTP 404", code)
        if code == 429:
            # TMDB asks clients to respect 429. The wait suggested by TMDB is
            # passed on to the caller, which decides whether to retry.
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            raise self._failure(tmdb_id, TmdbStatus.RATE_LIMITED, "HTTP 429", code, retry_after)
        if code != 200:
            raise self._failure(tmdb_id, TmdbStatus.UNAVAILABLE, f"HTTP {code}", code)

        try:
            data = response.json()
        except ValueError:
            raise self._failure(
                tmdb_id, TmdbStatus.INVALID_RESPONSE, "response is not valid JSON", code
            ) from None
        if not isinstance(data, dict):
            raise self._failure(
                tmdb_id, TmdbStatus.INVALID_RESPONSE, "response is not a JSON object", code
            )
        return parse_movie_details(data)

    @staticmethod
    def _failure(
        tmdb_id: int,
        status: TmdbStatus,
        reason: str,
        http_status: int | None = None,
        retry_after: float | None = None,
    ) -> TmdbError:
        # The access token is in a header and is never part of this message.
        logger.warning("TMDB lookup failed (tmdb_id=%s, status=%s): %s", tmdb_id, status, reason)
        return TmdbError(status, reason, http_status, retry_after)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "TmdbClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def fetch_movie_details_with_retry(
    client: TmdbClient,
    tmdb_id: int,
    max_retries: int = DEFAULT_MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> TmdbMovieDetails:
    """Call TMDB, retrying a limited number of times after temporary failures.

    - Only RETRYABLE_STATUSES are retried (429, timeouts, connection/5xx errors).
      A 404, an invalid answer or a rejected token is raised immediately.
    - After a 429 the wait is TMDB's Retry-After value when present; otherwise
      the wait doubles each time (1 s, 2 s, 4 s ...). Every wait is capped at
      MAX_RETRY_DELAY_SECONDS.
    - After `max_retries` retries the last TmdbError is raised, so there is
      never an infinite loop.

    `sleep` is injectable so tests run without real waiting.
    """
    attempt = 0
    while True:
        try:
            return client.get_movie_details(tmdb_id)
        except TmdbError as exc:
            if exc.status not in RETRYABLE_STATUSES or attempt >= max_retries:
                raise
            delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
            if exc.status is TmdbStatus.RATE_LIMITED and exc.retry_after is not None:
                delay = exc.retry_after
            sleep(min(delay, MAX_RETRY_DELAY_SECONDS))
            attempt += 1


def create_tmdb_client() -> TmdbClient:
    """Build a client from the application settings (token and timeout)."""
    settings = get_settings()
    token = settings.tmdb_api_read_access_token
    return TmdbClient(
        access_token=token.get_secret_value() if token is not None else None,
        timeout_seconds=settings.tmdb_timeout_seconds,
    )
