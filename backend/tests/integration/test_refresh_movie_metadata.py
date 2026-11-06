"""Tests for scripts/refresh_movie_metadata.py, with a mocked TMDB API.

The test catalogue has 17 movies; 16 have a TMDB ID (Dune (2000) has none).
"""

import logging
from datetime import date, timedelta

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models import MovieMetadata
from scripts import refresh_movie_metadata
from scripts.refresh_movie_metadata import is_refresh_due, refresh_metadata
from tests.helpers import TEST_MOVIES
from tests.tmdb_fakes import FAKE_TOKEN, NOW, FakeTmdbApi, SleepRecorder

pytestmark = pytest.mark.db

WITH_TMDB_ID = [m for m in TEST_MOVIES if m[3] is not None]
REFRESH_DAYS = 30


def run(db: Session, api: FakeTmdbApi, **options):
    """Run the refresh with test defaults: fixed clock, no real waiting."""
    reports: list[str] = []
    options = {
        "refresh_days": REFRESH_DAYS,
        "delay_seconds": 0,
        "clock": lambda: NOW,
        "sleep": SleepRecorder(),
        "report": reports.append,
    } | options
    summary = refresh_metadata(db, api.client, **options)
    return summary, reports


def stored(movie_id: int) -> MovieMetadata | None:
    """Read a row in a new session, i.e. only what was really committed."""
    with get_session_factory()() as db:
        row = db.get(MovieMetadata, movie_id)
        if row is not None:
            db.expunge(row)
        return row


def add_metadata(db: Session, movie_id: int, attempted_days_ago: float, **values) -> None:
    attempted = NOW - timedelta(days=attempted_days_ago)
    defaults = {
        "overview": "Old overview",
        "runtime": 90,
        "metadata_source": "tmdb",
        "metadata_updated_at": attempted,
        "refresh_status": "ok",
        "refresh_attempted_at": attempted,
    }
    db.add(MovieMetadata(movie_id=movie_id, **(defaults | values)))
    db.commit()


# --- Update policy (no database needed beyond the fixture) ----------------------


def test_update_policy():
    assert is_refresh_due(None, NOW, 30) is True
    assert is_refresh_due(MovieMetadata(movie_id=1), NOW, 30) is True  # Never attempted.
    recent = MovieMetadata(refresh_status="ok", refresh_attempted_at=NOW - timedelta(days=29))
    old = MovieMetadata(refresh_status="ok", refresh_attempted_at=NOW - timedelta(days=30))
    failed = MovieMetadata(refresh_status="timeout", refresh_attempted_at=NOW)
    missing = MovieMetadata(refresh_status="not_found", refresh_attempted_at=NOW)
    assert is_refresh_due(recent, NOW, 30) is False
    assert is_refresh_due(old, NOW, 30) is True
    assert is_refresh_due(failed, NOW, 30) is True  # Temporary failure: try again.
    assert is_refresh_due(missing, NOW, 30) is False  # 404: wait for the interval.


# --- New, expired and recent records ---------------------------------------------


def test_first_run_stores_metadata_for_every_movie_with_a_tmdb_id(db_session: Session):
    api = FakeTmdbApi()
    summary, _ = run(db_session, api)

    assert summary.selected == summary.refreshed == len(WITH_TMDB_ID)
    assert summary.skipped_no_tmdb_id == 1
    assert sorted(api.requested_ids) == sorted(m[3] for m in WITH_TMDB_ID)
    row = stored(1)
    assert (row.overview, row.release_date, row.runtime, row.poster_path) == (
        "Overview of Toy Story",
        date(1995, 10, 30),
        100,
        "/poster862.jpg",
    )
    assert (row.metadata_source, row.metadata_updated_at, row.refresh_status) == ("tmdb", NOW, "ok")
    assert row.refresh_attempted_at == NOW
    assert stored(7842) is None  # No TMDB ID: no row, no request.


def test_recent_records_are_skipped_and_expired_records_refreshed(db_session: Session):
    add_metadata(db_session, 1, attempted_days_ago=40)  # Expired.
    add_metadata(db_session, 2, attempted_days_ago=10)  # Recent.
    api = FakeTmdbApi()

    summary, _ = run(db_session, api, movie_ids=None)

    assert 862 in api.requested_ids
    assert 8844 not in api.requested_ids
    assert summary.skipped_recent == 1
    assert stored(1).overview == "Overview of Toy Story"
    assert stored(1).metadata_updated_at == NOW
    assert stored(2).overview == "Old overview"  # Untouched.


def test_second_run_makes_no_requests(db_session: Session):
    run(db_session, FakeTmdbApi())
    api = FakeTmdbApi()
    summary, _ = run(db_session, api)
    assert api.requests == []
    assert summary.selected == 0
    assert summary.skipped_recent == len(WITH_TMDB_ID)


def test_refresh_interval_is_configurable(db_session: Session):
    add_metadata(db_session, 1, attempted_days_ago=10)
    api = FakeTmdbApi()
    run(db_session, api, refresh_days=7, movie_ids=None)
    assert 862 in api.requested_ids


def test_explicit_movie_ids_are_refreshed_even_if_recent(db_session: Session):
    add_metadata(db_session, 1, attempted_days_ago=1)
    api = FakeTmdbApi()
    summary, _ = run(db_session, api, movie_ids=[1, 7842, 999_999])
    assert api.requested_ids == [862]
    assert summary.skipped_no_tmdb_id == 1
    assert summary.not_in_catalogue == [999_999]
    assert stored(1).metadata_updated_at == NOW


def test_values_no_longer_provided_by_tmdb_become_null(db_session: Session):
    add_metadata(db_session, 1, attempted_days_ago=40, poster_path="/old.jpg")
    api = FakeTmdbApi({862: httpx2.Response(200, json={"id": 862, "overview": "", "runtime": 0})})
    run(db_session, api, movie_ids=[1])
    row = stored(1)
    assert (row.overview, row.runtime, row.poster_path) == (None, None, None)
    assert row.metadata_updated_at == NOW  # Still a successful update.


# --- Failures --------------------------------------------------------------------------


def test_not_found_is_recorded_and_not_retried_before_the_interval(db_session: Session):
    api = FakeTmdbApi({862: httpx2.Response(404, json={"status_code": 34})})
    summary, _ = run(db_session, api)
    assert summary.not_found == 1
    row = stored(1)
    assert (row.refresh_status, row.metadata_updated_at) == ("not_found", None)

    again = FakeTmdbApi()
    run(db_session, again)
    assert 862 not in again.requested_ids


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (httpx2.Response(503), "unavailable"),
        (httpx2.ReadTimeout("slow"), "timeout"),
        (httpx2.ConnectError("refused"), "unavailable"),
        (httpx2.Response(200, content=b"<html>"), "invalid_response"),
        (httpx2.Response(429), "rate_limited"),
    ],
)
def test_temporary_failure_is_recorded_and_other_movies_continue(db_session, answer, status):
    api = FakeTmdbApi({862: answer})
    summary, _ = run(db_session, api, max_retries=1)

    assert summary.failed == {status: 1}
    assert summary.refreshed == len(WITH_TMDB_ID) - 1  # Partial failure only.
    assert stored(1).refresh_status == status
    assert stored(2).refresh_status == "ok"

    retry = FakeTmdbApi()
    run(db_session, retry)
    assert retry.requested_ids == [862]  # Temporary failures are tried again next run.
    assert stored(1).refresh_status == "ok"


def test_failed_refresh_keeps_previous_metadata(db_session: Session):
    add_metadata(db_session, 1, attempted_days_ago=40)
    api = FakeTmdbApi({862: httpx2.Response(500)})
    run(db_session, api, movie_ids=[1], max_retries=0)
    row = stored(1)
    assert row.overview == "Old overview"  # Not erased.
    assert row.metadata_updated_at == NOW - timedelta(days=40)
    assert (row.refresh_status, row.refresh_attempted_at) == ("unavailable", NOW)


def test_rate_limit_waits_for_retry_after_then_succeeds(db_session: Session):
    api = FakeTmdbApi(
        {862: [httpx2.Response(429, headers={"Retry-After": "2"}), httpx2.Response(200, json={})]}
    )
    sleep = SleepRecorder()
    summary, _ = run(db_session, api, movie_ids=[1], sleep=sleep)
    assert api.requested_ids == [862, 862]
    assert sleep.waits == [2.0]
    assert summary.refreshed == 1


def test_persistent_rate_limit_gives_up_after_max_retries(db_session: Session):
    api = FakeTmdbApi({862: httpx2.Response(429, headers={"Retry-After": "1"})})
    summary, _ = run(db_session, api, movie_ids=[1, 2], max_retries=2)
    assert api.requested_ids == [862, 862, 862, 8844]  # 1 + 2 retries, then the next movie.
    assert summary.failed == {"rate_limited": 1}
    assert summary.refreshed == 1


def test_rejected_token_stops_the_run_and_keeps_earlier_results(db_session: Session):
    api = FakeTmdbApi({8844: httpx2.Response(401, json={"status_code": 7})})
    summary, _ = run(db_session, api, batch_size=50)
    assert api.requested_ids == [862, 8844]  # Stopped at once: no further requests.
    assert summary.aborted_reason is not None and "token" in summary.aborted_reason.lower()
    assert stored(1).refresh_status == "ok"  # Committed before stopping.
    assert stored(2) is None  # Authentication errors are never stored.


# --- Batches, interruption and resumption -----------------------------------------------


def test_results_are_committed_per_batch_with_progress_reports(db_session: Session):
    summary, reports = run(db_session, FakeTmdbApi(), batch_size=4)
    batches = [line for line in reports if line.startswith("Batch ")]
    assert batches[0] == f"Batch 1/4: 4/{len(WITH_TMDB_ID)} processed"
    assert batches[-1] == f"Batch 4/4: {len(WITH_TMDB_ID)}/{len(WITH_TMDB_ID)} processed"
    assert summary.processed == len(WITH_TMDB_ID)


def test_requests_are_sequential_with_a_delay_between_them(db_session: Session):
    sleep = SleepRecorder()
    run(db_session, FakeTmdbApi(), movie_ids=[1, 2, 3], delay_seconds=0.25, sleep=sleep)
    assert sleep.waits == [0.25, 0.25]  # Between requests, not before the first one.


def test_limit_restricts_the_number_of_lookups(db_session: Session):
    api = FakeTmdbApi()
    summary, _ = run(db_session, api, limit=3)
    assert len(api.requests) == summary.selected == 3


def test_interruption_keeps_finished_work_and_the_next_run_resumes(db_session: Session):
    def interrupt():
        raise KeyboardInterrupt

    api = FakeTmdbApi({15602: interrupt})  # The third movie (ID 3) is interrupted.
    summary, _ = run(db_session, api, batch_size=50)
    assert summary.interrupted is True
    assert summary.processed == 2
    assert stored(1).refresh_status == stored(2).refresh_status == "ok"  # Saved.
    assert stored(3) is None

    resumed = FakeTmdbApi()
    run(db_session, resumed)
    assert 862 not in resumed.requested_ids  # Not requested again.
    assert 15602 in resumed.requested_ids
    with get_session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(MovieMetadata)) == len(WITH_TMDB_ID)


# --- Output and credentials ------------------------------------------------------------


def test_summary_lists_all_counts(db_session: Session):
    api = FakeTmdbApi({862: httpx2.Response(404), 8844: httpx2.Response(503)})
    summary, _ = run(db_session, api, max_retries=0)
    text = "\n".join(summary.lines())
    assert f"Selected for lookup:          {len(WITH_TMDB_ID)}" in text
    assert f"Metadata stored/updated:      {len(WITH_TMDB_ID) - 2}" in text
    assert "Not found on TMDB (404):      1" in text
    assert "Temporary failures:           1 (unavailable=1)" in text
    assert "Skipped (no TMDB ID):         1" in text


def test_token_never_appears_in_output_or_logs(db_session: Session, caplog):
    api = FakeTmdbApi({862: httpx2.Response(401), 8844: httpx2.Response(503)})
    with caplog.at_level(logging.DEBUG):
        summary, reports = run(db_session, api, movie_ids=[2, 1], max_retries=0)
    everything = "\n".join(reports + summary.lines()) + caplog.text
    assert FAKE_TOKEN not in everything
    assert api.requests[0].headers["Authorization"] == f"Bearer {FAKE_TOKEN}"  # Sent in a header.
    assert all(FAKE_TOKEN not in str(request.url) for request in api.requests)


# --- Command line ----------------------------------------------------------------------


def test_command_line_without_token_sends_no_request(clean_db, capsys):
    assert refresh_movie_metadata.main([]) == 1
    assert "TMDB_API_READ_ACCESS_TOKEN is not set" in capsys.readouterr().err


@pytest.fixture
def configured_token(monkeypatch):
    monkeypatch.setenv("TMDB_API_READ_ACCESS_TOKEN", FAKE_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()  # monkeypatch then restores the empty test value.


def test_command_line_run_prints_a_summary(clean_db, configured_token, monkeypatch, capsys):
    api = FakeTmdbApi()
    monkeypatch.setattr("app.services.tmdb_service.create_tmdb_client", lambda: api.client)
    assert refresh_movie_metadata.main(["--movie-id", "1", "--batch-size", "10"]) == 0
    output = capsys.readouterr().out
    assert "Metadata stored/updated:      1" in output
    assert FAKE_TOKEN not in output
    assert stored(1).refresh_status == "ok"


def test_command_line_returns_error_when_the_token_is_rejected(
    clean_db, configured_token, monkeypatch, capsys
):
    api = FakeTmdbApi({862: httpx2.Response(401)})
    monkeypatch.setattr("app.services.tmdb_service.create_tmdb_client", lambda: api.client)
    assert refresh_movie_metadata.main(["--movie-id", "1"]) == 1
    assert "Stopped early" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [["--batch-size", "0"], ["--delay", "-1"], ["--max-retries", "9"], ["--limit", "x"]],
)
def test_command_line_rejects_invalid_options(clean_db, arguments):
    with pytest.raises(SystemExit):
        refresh_movie_metadata.main(arguments)


def test_command_line_returns_130_after_ctrl_c(clean_db, configured_token, monkeypatch, capsys):
    def interrupt():
        raise KeyboardInterrupt

    api = FakeTmdbApi({8844: interrupt})
    monkeypatch.setattr("app.services.tmdb_service.create_tmdb_client", lambda: api.client)
    assert (
        refresh_movie_metadata.main(["--movie-id", "1", "--movie-id", "2", "--delay", "0"]) == 130
    )
    assert "Interrupted" in capsys.readouterr().out
    assert stored(1).refresh_status == "ok"  # Work done before Ctrl+C was saved.
