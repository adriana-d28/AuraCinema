"""Tests for scripts/validate_tmdb_ids.py, with a mocked TMDB API.

The test catalogue has 17 movies; 16 have a TMDB ID (Dune (2000) has none).
"""

import logging
from datetime import timedelta

import httpx2
import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models import Movie, MovieMetadata
from scripts import validate_tmdb_ids
from scripts.refresh_movie_metadata import refresh_metadata
from scripts.seed_movies import MovieRecord, import_movies
from scripts.validate_tmdb_ids import is_validation_due
from tests.helpers import TEST_MOVIES
from tests.tmdb_fakes import FAKE_TOKEN, NOW, FakeTmdbApi, SleepRecorder, details_json

pytestmark = pytest.mark.db

WITH_TMDB_ID = [m for m in TEST_MOVIES if m[3] is not None]


def run(db: Session, api: FakeTmdbApi, **options):
    reports: list[str] = []
    options = {
        "delay_seconds": 0,
        "clock": lambda: NOW,
        "sleep": SleepRecorder(),
        "report": reports.append,
    } | options
    return validate_tmdb_ids.validate_tmdb_ids(db, api.client, **options), reports


def stored(movie_id: int) -> MovieMetadata | None:
    with get_session_factory()() as db:
        row = db.get(MovieMetadata, movie_id)
        if row is not None:
            db.expunge(row)
        return row


def test_selection_rules():
    assert is_validation_due(None) is True
    assert is_validation_due(MovieMetadata(tmdb_validation_status="not_checked")) is True
    assert is_validation_due(MovieMetadata(tmdb_validation_status="temporary_error")) is True
    for final in ("valid", "not_found", "title_mismatch", "year_mismatch", "ambiguous"):
        assert is_validation_due(MovieMetadata(tmdb_validation_status=final)) is False
    ambiguous = MovieMetadata(tmdb_validation_status="ambiguous")
    assert is_validation_due(ambiguous, frozenset({"ambiguous"})) is True


# --- Results ----------------------------------------------------------------------


def test_first_run_validates_every_movie_with_a_tmdb_id(db_session: Session):
    api = FakeTmdbApi()
    summary, _ = run(db_session, api)

    assert summary.selected == summary.processed == len(WITH_TMDB_ID)
    assert summary.results == {"valid": len(WITH_TMDB_ID)}  # The fake data matches.
    assert summary.skipped_no_tmdb_id == 1
    row = stored(2571)
    assert (row.tmdb_validation_status, row.tmdb_validation_http_status) == ("valid", 200)
    assert row.tmdb_validated_at == NOW
    assert "match" in row.tmdb_validation_note
    assert stored(7842) is None  # Missing TMDB ID: skipped, nothing stored.


@pytest.mark.parametrize(
    ("answer", "status", "http_status"),
    [
        (httpx2.Response(404, json={"status_code": 34}), "not_found", 404),
        (httpx2.Response(200, json=details_json(862, title="Avatar", original_title="Avatar")),
         "title_mismatch", 200),
        (httpx2.Response(200, json=details_json(862, release_date="2019-06-20")),
         "year_mismatch", 200),
        (httpx2.Response(200, json=details_json(862, title="Toy Story: The Movie Collection",
                                                original_title=None)), "ambiguous", 200),
        (httpx2.Response(503), "temporary_error", 503),
        (httpx2.ReadTimeout("slow"), "temporary_error", None),
        (httpx2.Response(429), "temporary_error", 429),
        (httpx2.Response(200, content=b"not json"), "temporary_error", 200),
    ],
)  # fmt: skip
def test_each_outcome_is_stored(db_session, answer, status, http_status):
    api = FakeTmdbApi({862: answer})
    summary, _ = run(db_session, api, movie_ids=[1], max_retries=0)
    row = stored(1)
    assert (row.tmdb_validation_status, row.tmdb_validation_http_status) == (status, http_status)
    assert row.tmdb_validation_note
    assert summary.results == {status: 1}


def test_movie_id_is_never_replaced(db_session: Session):
    api = FakeTmdbApi(
        {862: httpx2.Response(200, json=details_json(862, title="Avatar", original_title=None))}
    )
    run(db_session, api, movie_ids=[1])
    db_session.expire_all()
    assert db_session.get(Movie, 1).tmdb_id == 862  # Only flagged, never changed.


# --- Incremental behaviour ------------------------------------------------------------


def test_previously_validated_records_are_skipped(db_session: Session):
    run(db_session, FakeTmdbApi())
    again = FakeTmdbApi()
    summary, _ = run(db_session, again)
    assert again.requests == []
    assert summary.skipped_already_validated == len(WITH_TMDB_ID)


def test_new_catalogue_movie_is_the_only_one_validated(db_session: Session):
    run(db_session, FakeTmdbApi())
    import_movies(db_session, [MovieRecord(500_000, "Avatar (2009)", "Sci-Fi", 19995, None)])
    api = FakeTmdbApi(
        {19995: httpx2.Response(200, json={"title": "Avatar", "release_date": "2009-12-15"})}
    )
    summary, _ = run(db_session, api)
    assert api.requested_ids == [19995]
    assert stored(500_000).tmdb_validation_status == "valid"


def test_changed_tmdb_id_is_validated_again(db_session: Session):
    run(db_session, FakeTmdbApi())
    import_movies(db_session, [MovieRecord(1, "Toy Story (1995)", "Comedy", 8844, 114709)])
    api = FakeTmdbApi()
    run(db_session, api)
    assert api.requested_ids == [8844]  # The import reset the old result.
    assert stored(1).tmdb_validation_status == "title_mismatch"  # 8844 is Jumanji.


def test_temporary_errors_are_checked_again_on_the_next_run(db_session: Session):
    run(db_session, FakeTmdbApi({862: httpx2.Response(500)}), max_retries=0)
    assert stored(1).tmdb_validation_status == "temporary_error"
    api = FakeTmdbApi()
    run(db_session, api)
    assert api.requested_ids == [862]
    assert stored(1).tmdb_validation_status == "valid"


def test_final_failures_are_not_checked_again_automatically(db_session: Session):
    run(db_session, FakeTmdbApi({862: httpx2.Response(404)}))
    api = FakeTmdbApi()
    run(db_session, api)
    assert 862 not in api.requested_ids


def test_explicit_revalidation_of_selected_records(db_session: Session):
    run(db_session, FakeTmdbApi())
    api = FakeTmdbApi()
    summary, _ = run(db_session, api, movie_ids=[2571, 999_999])
    assert api.requested_ids == [603]
    assert summary.not_in_catalogue == [999_999]


def test_recheck_revalidates_a_group_of_results(db_session: Session):
    title = "Toy Story: The Movie Collection"
    run(
        db_session,
        FakeTmdbApi(
            {862: httpx2.Response(200, json=details_json(862, title=title, original_title=None))}
        ),
    )
    assert stored(1).tmdb_validation_status == "ambiguous"
    api = FakeTmdbApi()
    run(db_session, api, recheck=["ambiguous"])
    assert api.requested_ids == [862]
    assert stored(1).tmdb_validation_status == "valid"


# --- Separation from the metadata refresh ------------------------------------------------


def test_validation_and_refresh_do_not_overwrite_each_other(db_session: Session):
    refresh_metadata(
        db_session, FakeTmdbApi().client, 30, movie_ids=[1], delay_seconds=0, report=lambda _: None
    )
    wrong = details_json(862, title="X", original_title="X")
    run(db_session, FakeTmdbApi({862: httpx2.Response(200, json=wrong)}), movie_ids=[1])
    row = stored(1)
    assert row.tmdb_validation_status == "title_mismatch"
    assert (row.overview, row.refresh_status) == ("Overview of Toy Story", "ok")  # Kept.

    later = NOW + timedelta(days=60)
    refresh_metadata(
        db_session,
        FakeTmdbApi().client,
        30,
        movie_ids=[1],
        delay_seconds=0,
        clock=lambda: later,
        report=lambda _: None,
    )
    row = stored(1)
    assert row.metadata_updated_at == later
    assert row.tmdb_validation_status == "title_mismatch"  # Not reset by the refresh.


# --- Batches, interruption, rate limits ----------------------------------------------------


def test_rejected_token_stops_the_run(db_session: Session):
    api = FakeTmdbApi({8844: httpx2.Response(401)})
    summary, _ = run(db_session, api)
    assert api.requested_ids == [862, 8844]
    assert summary.aborted_reason is not None
    assert stored(1).tmdb_validation_status == "valid"
    assert stored(2) is None


def test_summary_and_logs_never_contain_the_token(db_session: Session, caplog):
    api = FakeTmdbApi({862: httpx2.Response(404), 8844: httpx2.Response(503)})
    with caplog.at_level(logging.DEBUG):
        summary, reports = run(db_session, api, max_retries=0)
    text = "\n".join(reports + summary.lines())
    assert "Selected for validation:        16" in text
    assert "not_found:                      1" in text
    assert "temporary_error:                1" in text
    assert "valid:                          14" in text
    assert FAKE_TOKEN not in text + caplog.text


# --- Command line ----------------------------------------------------------------------


def test_command_line_without_token_sends_no_request(clean_db, capsys):
    assert validate_tmdb_ids.main([]) == 1
    assert "TMDB_API_READ_ACCESS_TOKEN is not set" in capsys.readouterr().err


def test_command_line_run(clean_db, monkeypatch, capsys):
    monkeypatch.setenv("TMDB_API_READ_ACCESS_TOKEN", FAKE_TOKEN)
    get_settings.cache_clear()
    api = FakeTmdbApi()
    monkeypatch.setattr("app.services.tmdb_service.create_tmdb_client", lambda: api.client)
    try:
        assert validate_tmdb_ids.main(["--movie-id", "2571", "--recheck", "ambiguous"]) == 0
    finally:
        get_settings.cache_clear()
    output = capsys.readouterr().out
    assert "valid:" in output and FAKE_TOKEN not in output
    assert stored(2571).tmdb_validation_status == "valid"


def test_command_line_rejects_unknown_recheck_status(clean_db):
    with pytest.raises(SystemExit):
        validate_tmdb_ids.main(["--recheck", "not_checked"])
