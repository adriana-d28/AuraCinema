"""A fake TMDB API for the maintenance-script tests (no network access)."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx2

from app.services.tmdb_service import TmdbClient

FAKE_TOKEN = "fake-tmdb-token-used-only-in-tests-0123456789"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)

# TMDB answers for the movies of the test catalogue (tests/helpers.py), keyed by TMDB ID.
TMDB_MOVIES = {
    862: {"title": "Toy Story", "original_title": "Toy Story", "release_date": "1995-10-30"},
    8844: {"title": "Jumanji", "original_title": "Jumanji", "release_date": "1995-12-15"},
    15602: {"title": "Grumpier Old Men", "release_date": "1995-12-22"},
    11862: {"title": "Father of the Bride Part II", "release_date": "1995-12-08"},
    949: {"title": "Heat", "release_date": "1995-12-15"},
    11860: {"title": "Sabrina", "release_date": "1995-12-15"},
    710: {"title": "GoldenEye", "release_date": "1995-11-16"},
    11517: {"title": "Money Train", "release_date": "1995-11-21"},
    902: {
        "title": "The City of Lost Children",
        "original_title": "La Cité des enfants perdus",
        "release_date": "1995-05-17",
    },
    37557: {
        "title": "Shanghai Triad",
        "original_title": "摇啊摇，摇到外婆桥",
        "release_date": "1995-04-30",
    },
    101: {
        "title": "Léon: The Professional",
        "original_title": "Léon",
        "release_date": "1994-09-14",
    },
    278: {"title": "The Shawshank Redemption", "release_date": "1994-09-23"},
    100: {"title": "Lock, Stock and Two Smoking Barrels", "release_date": "1998-03-05"},
    603: {"title": "The Matrix", "release_date": "1999-03-31"},
    863: {"title": "Toy Story 2", "release_date": "1999-10-30"},
    10193: {"title": "Toy Story 3", "release_date": "2010-06-16"},
}


def details_json(tmdb_id: int, **overrides) -> dict:
    base = TMDB_MOVIES.get(tmdb_id, {"title": f"Movie {tmdb_id}"})
    return {
        "id": tmdb_id,
        "overview": f"Overview of {base['title']}",
        "runtime": 100,
        "poster_path": f"/poster{tmdb_id}.jpg",
        **base,
        **overrides,
    }


Answer = httpx2.Response | Exception | Callable[[], httpx2.Response]


class FakeTmdbApi:
    """Answers /movie/{id} from TMDB_MOVIES unless a special answer is configured.

    `answers[tmdb_id]` may be a single answer or a list used one per request
    (the last one is repeated). Every request is recorded.
    """

    def __init__(self, answers: dict[int, Answer | list[Answer]] | None = None) -> None:
        self.answers = answers or {}
        self.requests: list[httpx2.Request] = []
        self.client = TmdbClient(
            access_token=FAKE_TOKEN, timeout_seconds=5, transport=httpx2.MockTransport(self._handle)
        )

    @property
    def requested_ids(self) -> list[int]:
        return [int(request.url.path.rsplit("/", 1)[-1]) for request in self.requests]

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        tmdb_id = int(request.url.path.rsplit("/", 1)[-1])
        answer = self.answers.get(tmdb_id)
        if isinstance(answer, list):
            count = self.requested_ids.count(tmdb_id)
            answer = answer[min(count, len(answer)) - 1]
        if answer is None:
            return httpx2.Response(200, json=details_json(tmdb_id))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer()
        return answer


class SleepRecorder:
    """Replaces time.sleep: records the waits instead of waiting."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
