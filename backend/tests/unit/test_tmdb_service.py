"""Unit tests for the TMDB client and its retry helper.

No real network requests are made: httpx2.MockTransport answers every
request with a prepared response, and a fake sleep function records waits.
"""

import logging
from datetime import date

import httpx2
import pytest

from app.services.tmdb_service import (
    MAX_RETRY_DELAY_SECONDS,
    TmdbClient,
    TmdbError,
    TmdbMovieDetails,
    TmdbStatus,
    fetch_movie_details_with_retry,
    parse_movie_details,
    parse_retry_after,
)

TOKEN = "test-tmdb-token-not-a-real-credential"

# Shape of a real TMDB movie-details answer (shortened; extra fields are ignored).
TOY_STORY_JSON = {
    "id": 862,
    "title": "Toy Story",
    "overview": "Led by Woody, Andy's toys live happily in his room...",
    "release_date": "1995-10-30",
    "runtime": 81,
    "poster_path": "/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
    "genres": [{"id": 16, "name": "Animation"}],
    "vote_average": 8.0,
}


class RecordingHandler:
    """MockTransport handler that records requests and returns a fixed answer."""

    def __init__(self, response: httpx2.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_client(handler: RecordingHandler, token: str | None = TOKEN) -> TmdbClient:
    return TmdbClient(
        access_token=token, timeout_seconds=5, transport=httpx2.MockTransport(handler)
    )


# --- Successful responses and field mapping ---------------------------------


def test_successful_response_is_mapped_to_movie_details():
    handler = RecordingHandler(httpx2.Response(200, json=TOY_STORY_JSON))
    details = make_client(handler).get_movie_details(862)

    assert details == TmdbMovieDetails(
        overview="Led by Woody, Andy's toys live happily in his room...",
        release_date=date(1995, 10, 30),
        runtime=81,
        poster_path="/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg",
        title="Toy Story",
        original_title=None,  # Not present in this shortened answer.
    )
    assert details.poster_url == "https://image.tmdb.org/t/p/w500/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg"


def test_request_uses_movie_details_url_and_bearer_token():
    handler = RecordingHandler(httpx2.Response(200, json=TOY_STORY_JSON))
    make_client(handler).get_movie_details(862)

    (request,) = handler.requests
    assert request.method == "GET"
    assert str(request.url) == "https://api.themoviedb.org/3/movie/862"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    # The credential is sent in a header, never in the URL.
    assert TOKEN not in str(request.url)


def test_missing_optional_fields_become_none():
    handler = RecordingHandler(httpx2.Response(200, json={"id": 862}))
    details = make_client(handler).get_movie_details(862)
    assert details == TmdbMovieDetails(None, None, None, None)
    assert details.poster_url is None


@pytest.mark.parametrize(
    "data",
    [
        # TMDB's own "unknown" values.
        {"overview": "", "release_date": "", "runtime": 0, "poster_path": None},
        # Unexpected types or formats are treated as missing, not as errors.
        {"overview": 42, "release_date": "30/10/1995", "runtime": "81", "poster_path": "x.jpg"},
        {"overview": None, "release_date": None, "runtime": True, "poster_path": "/"},
    ],
)
def test_empty_or_unexpected_field_values_become_none(data):
    assert parse_movie_details(data) == TmdbMovieDetails(None, None, None, None)


# --- Error handling ---------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, TmdbStatus.AUTH_FAILED),
        (403, TmdbStatus.AUTH_FAILED),
        (404, TmdbStatus.NOT_FOUND),
        (429, TmdbStatus.RATE_LIMITED),
        (500, TmdbStatus.UNAVAILABLE),
        (503, TmdbStatus.UNAVAILABLE),
        (302, TmdbStatus.UNAVAILABLE),
    ],
)
def test_http_errors_raise_tmdb_error_with_status(status_code, expected):
    handler = RecordingHandler(httpx2.Response(status_code, json={"status_code": 7}))
    with pytest.raises(TmdbError) as error:
        make_client(handler).get_movie_details(862)
    assert error.value.status == expected


def test_connection_failure_raises_unavailable():
    handler = RecordingHandler(httpx2.ConnectError("connection refused"))
    with pytest.raises(TmdbError) as error:
        make_client(handler).get_movie_details(862)
    assert error.value.status is TmdbStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "exception", [httpx2.ReadTimeout("read timed out"), httpx2.ConnectTimeout("timed out")]
)
def test_timeout_raises_timeout(exception):
    handler = RecordingHandler(exception)
    with pytest.raises(TmdbError) as error:
        make_client(handler).get_movie_details(862)
    assert error.value.status is TmdbStatus.TIMEOUT


def test_configured_timeout_is_applied_to_requests():
    handler = RecordingHandler(httpx2.Response(200, json=TOY_STORY_JSON))
    client = TmdbClient(TOKEN, timeout_seconds=2.5, transport=httpx2.MockTransport(handler))
    client.get_movie_details(862)
    timeout = handler.requests[0].extensions["timeout"]
    assert timeout == {"connect": 2.5, "read": 2.5, "write": 2.5, "pool": 2.5}


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, content=b"<html>not json</html>"),
        httpx2.Response(200, content=b'{"overview": "cut off'),
        httpx2.Response(200, json=["a", "list", "instead", "of", "an", "object"]),
        httpx2.Response(200, json=None),
    ],
)
def test_invalid_json_raises_invalid_response(response):
    handler = RecordingHandler(response)
    with pytest.raises(TmdbError) as error:
        make_client(handler).get_movie_details(862)
    assert error.value.status is TmdbStatus.INVALID_RESPONSE


def test_missing_credential_raises_not_configured_without_network_call():
    handler = RecordingHandler(httpx2.Response(200, json=TOY_STORY_JSON))
    client = make_client(handler, token=None)
    assert client.is_configured is False
    with pytest.raises(TmdbError) as error:
        client.get_movie_details(862)
    assert error.value.status is TmdbStatus.NOT_CONFIGURED
    assert handler.requests == []


def test_failures_are_logged_without_the_token(caplog):
    handler = RecordingHandler(httpx2.Response(401, json={"status_code": 7}))
    with caplog.at_level(logging.DEBUG), pytest.raises(TmdbError):
        make_client(handler).get_movie_details(862)
    assert "tmdb_id=862" in caplog.text
    assert TOKEN not in caplog.text


def test_titles_are_kept_for_validation_only():
    details = parse_movie_details(
        {"title": "Léon: The Professional", "original_title": "Léon", "overview": "x"}
    )
    assert (details.title, details.original_title) == ("Léon: The Professional", "Léon")


def test_http_status_is_attached_to_the_error():
    handler = RecordingHandler(httpx2.Response(404, json={"status_code": 34}))
    with pytest.raises(TmdbError) as error:
        make_client(handler).get_movie_details(1)
    assert error.value.http_status == 404


def test_rate_limit_error_carries_retry_after_seconds():
    handler = RecordingHandler(httpx2.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(TmdbError) as error:
        make_client(handler).get_movie_details(862)
    assert error.value.status is TmdbStatus.RATE_LIMITED
    assert error.value.retry_after == 7.0


@pytest.mark.parametrize(
    ("header", "expected"),
    [("5", 5.0), (" 2.5 ", 2.5), ("0", 0.0), (None, None), ("soon", None), ("-3", None),
     ("Wed, 21 Oct 2026 07:28:00 GMT", None), ("nan", None)],
)  # fmt: skip
def test_parse_retry_after(header, expected):
    assert parse_retry_after(header) == expected


# --- fetch_movie_details_with_retry ------------------------------------------


class SequenceHandler:
    """Returns the prepared answers one after the other."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, Exception):
            raise response
        return response


def retry_client(handler: SequenceHandler) -> TmdbClient:
    return TmdbClient(TOKEN, 5, transport=httpx2.MockTransport(handler))


def test_retry_waits_for_retry_after_and_then_succeeds():
    handler = SequenceHandler(
        httpx2.Response(429, headers={"Retry-After": "3"}),
        httpx2.Response(200, json=TOY_STORY_JSON),
    )
    waits: list[float] = []
    details = fetch_movie_details_with_retry(retry_client(handler), 862, sleep=waits.append)
    assert details.runtime == 81
    assert waits == [3.0]  # TMDB's own guidance was respected.
    assert handler.calls == 2


def test_retry_uses_exponential_backoff_without_retry_after():
    handler = SequenceHandler(
        httpx2.ReadTimeout("slow"),
        httpx2.Response(503),
        httpx2.Response(429),
        httpx2.Response(200, json=TOY_STORY_JSON),
    )
    waits: list[float] = []
    fetch_movie_details_with_retry(retry_client(handler), 862, max_retries=3, sleep=waits.append)
    assert waits == [1.0, 2.0, 4.0]


def test_retry_gives_up_after_max_retries():
    handler = SequenceHandler(httpx2.Response(429))
    waits: list[float] = []
    with pytest.raises(TmdbError) as error:
        fetch_movie_details_with_retry(
            retry_client(handler), 862, max_retries=2, sleep=waits.append
        )
    assert error.value.status is TmdbStatus.RATE_LIMITED
    assert handler.calls == 3  # One attempt plus two retries: never an infinite loop.
    assert len(waits) == 2


def test_retry_after_is_capped():
    handler = SequenceHandler(
        httpx2.Response(429, headers={"Retry-After": "86400"}),
        httpx2.Response(200, json=TOY_STORY_JSON),
    )
    waits: list[float] = []
    fetch_movie_details_with_retry(retry_client(handler), 862, sleep=waits.append)
    assert waits == [MAX_RETRY_DELAY_SECONDS]


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (httpx2.Response(404), TmdbStatus.NOT_FOUND),
        (httpx2.Response(401), TmdbStatus.AUTH_FAILED),
        (httpx2.Response(200, content=b"not json"), TmdbStatus.INVALID_RESPONSE),
    ],
)
def test_permanent_failures_are_not_retried(response, status):
    handler = SequenceHandler(response)
    waits: list[float] = []
    with pytest.raises(TmdbError) as error:
        fetch_movie_details_with_retry(retry_client(handler), 862, sleep=waits.append)
    assert error.value.status is status
    assert handler.calls == 1
    assert waits == []


def test_client_factory_uses_the_settings_without_a_token():
    # The test environment forces an empty token, so the client is "not configured"
    # and refuses to send any request.
    from app.services.tmdb_service import create_tmdb_client

    with create_tmdb_client() as client:
        assert client.is_configured is False
        with pytest.raises(TmdbError) as error:
            client.get_movie_details(862)
    assert error.value.status is TmdbStatus.NOT_CONFIGURED
