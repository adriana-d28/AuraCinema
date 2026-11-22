"""Recommendation service: connects the users' stored ratings to the trained ML models.

The machine-learning work is NOT done here. The two recommenders were built and
evaluated offline in the ML component (ml/src) and saved as small versioned files in
ml/data/models (see MODEL_DIR below):

- item-based collaborative filtering (CF), loaded with ``load_cf_model`` and used
  through ``recommend_movies``;
- the popularity baseline, loaded with ``load_popularity_baseline`` and used
  through ``top_n_popular_movies``.

This module only (1) loads those files once, (2) reads the current user's ratings
from PostgreSQL, (3) decides which recommender suits the user, (4) calls it, and
(5) turns the returned (movieId, score) pairs into API objects with the existing
catalogue helper ``movie_service.build_recommended_movies``.

Cold start vs. loading failure are deliberately treated differently:
- a user with too little rating history gets the popularity list ON PURPOSE;
- if the model a user needs could not be loaded, the request fails with
  ``RecommendationUnavailableError`` (HTTP 503). The other model is never used
  silently in its place.
"""

import logging
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache, partial
from pathlib import Path

from sqlalchemy.orm import Session

from app.schemas.recommendation import RecommendationResponse, RecommendationSource
from app.services import movie_service, rating_service

logger = logging.getLogger(__name__)

# The ML component lives next to the backend: <repository>/ml. Its package is
# called "src" and imports itself as "src.<module>", so the ml/ folder must be on
# Python's import path. The Docker image copies the same layout, so this path is
# valid both in a repository clone and inside the container.
ML_DIR = Path(__file__).resolve().parents[3] / "ml"

# Every file needed at runtime is in this one versioned folder:
#   cf_item_neighbours.npz, cf_model_manifest.json   -> CF model
#   movie_index_map.csv                              -> CF item_index <-> movieId mapping
#   popularity_baseline.csv, popularity_baseline_manifest.json -> popularity baseline
# The mapping is a copy of the one the CF model was trained with. By default
# load_cf_model() would look for it in ml/data/processed/, a git-ignored folder that
# also holds the large training and test datasets. The API therefore points the
# loader at this folder instead. The loader still checks the copy against the SHA-256
# recorded in cf_model_manifest.json, so a stale or edited mapping is rejected.
# Runtime never needs the training or test datasets.
MODEL_DIR = ML_DIR / "data" / "models"

# Cold-start rule (the only place where it is defined; see
# backend/docs/recommendation_service_integration.md, Section 6):
# CF is used when the user has at least this many ratings AND not all of them have
# the same value. Otherwise the popularity baseline is used.
#
# Why "not all the same value"? The CF model scores a movie from the user's rating
# DEVIATIONS from their own average (rating - user's mean). If every rating is equal
# (which is always true for a single rating), every deviation is 0, every CF score
# is 0, and the "ranking" would just be the movieId tie-break, not a preference.
MIN_RATINGS_FOR_CF = 2

COLD_START_MESSAGE = "Discover popular movies while we get to know your taste!"

# Signatures of the two loaded recommenders, as used by this service:
#   cf(history, n)                         -> [(movieId, score), ...] best first
#   popularity(n, exclude_movie_ids=ids)   -> [(movieId, score), ...] best first
CfRecommender = Callable[[Mapping[int, float], int], list[tuple[int, float]]]
PopularityRecommender = Callable[..., list[tuple[int, float]]]


@dataclass(frozen=True)
class Recommenders:
    """The loaded recommenders; None means "could not be loaded at start-up".

    Each one is the ML component's public recommendation function with its loaded
    model already bound to it (functools.partial). The service therefore never
    sees internal model structures such as the item_index, and the tests can pass
    simple fake functions instead of real models.
    """

    cf: CfRecommender | None
    popularity: PopularityRecommender | None


class RecommendationUnavailableError(Exception):
    """The recommender needed for this user is not loaded (missing or invalid files)."""


def _import_ml_modules():
    """Import the ML component's modules (only when the models are loaded).

    Importing here, rather than at the top of the file, means that a missing ML
    folder or a missing scientific package (numpy, pandas, scipy) is logged as a
    loading error instead of preventing the whole API from starting.
    """
    if str(ML_DIR) not in sys.path:
        # Appended (not inserted first) so the backend's own packages always win.
        sys.path.append(str(ML_DIR))
    from src import collaborative_filtering, popularity_baseline

    return collaborative_filtering, popularity_baseline


@lru_cache(maxsize=1)
def load_recommenders() -> Recommenders:
    """Load both recommenders from their saved files, once per process.

    ``lru_cache`` turns this into a "load once, then reuse" function: the first call
    reads and verifies the files (the ML loaders check the SHA-256 hashes stored in
    the manifests and validate the contents), and every later call returns the same
    objects. It is called at application start-up (see ``app.main``) and then used
    as a FastAPI dependency by the recommendation endpoint.

    The two models are loaded independently, so a problem with one does not disable
    the other. Problems are logged in full on the server (with paths, for the
    developer); API clients only ever see a generic 503 message.
    """
    try:
        cf_module, popularity_module = _import_ml_modules()
    except ImportError:
        logger.exception("Could not import the ML component from %s", ML_DIR)
        return Recommenders(cf=None, popularity=None)

    cf = popularity = None
    try:
        model, manifest = cf_module.load_cf_model(MODEL_DIR, processed_dir=MODEL_DIR)
        cf = partial(cf_module.recommend_movies, model)
        logger.info(
            "Collaborative filtering model loaded (version %s, k=%s, scoring=%s)",
            manifest["model"]["version"],
            model.n_neighbours,
            model.scoring,
        )
    except Exception:
        # Any failure (file missing, hash mismatch, invalid matrix, ...) is reported
        # and the model stays unavailable; it is never replaced by another model.
        logger.exception("Could not load the collaborative filtering model")

    try:
        ranking, manifest = popularity_module.load_popularity_baseline(MODEL_DIR)
        popularity = partial(popularity_module.top_n_popular_movies, ranking)
        logger.info(
            "Popularity baseline loaded (version %s, %d movies)",
            manifest["baseline"]["version"],
            len(ranking),
        )
    except Exception:
        logger.exception("Could not load the popularity baseline")

    return Recommenders(cf=cf, popularity=popularity)


def get_rating_history(db: Session, user_id: int) -> dict[int, float]:
    """The user's current ratings in the format of the ML component: {movieId: rating}.

    Reuses ``rating_service.list_ratings``, which filters by the given user ID. The
    route passes the ID of the authenticated user, so only that user's ratings are
    ever used. There is one row per (user, movie) and re-rating updates that row, so
    each movie appears once with its current value, on the original 0.5-5.0 scale.
    """
    return {rating.movie_id: rating.rating for rating in rating_service.list_ratings(db, user_id)}


def has_enough_history_for_cf(history: Mapping[int, float]) -> bool:
    """Cold-start decision: True = collaborative filtering, False = popularity.

    See ``MIN_RATINGS_FOR_CF`` for the rule and why identical ratings count as
    insufficient history.
    """
    return len(history) >= MIN_RATINGS_FOR_CF and len(set(history.values())) > 1


def recommend_for_user(
    db: Session, user_id: int, limit: int, recommenders: Recommenders
) -> RecommendationResponse:
    """Build the recommendation response for one user.

    Steps:
    1. read the user's ratings ({movieId: rating});
    2. choose CF or popularity with the cold-start rule;
    3. ask the chosen recommender for ``limit`` (movieId, score) pairs; both
       recommenders already leave out the movies the user has rated;
    4. resolve the IDs against the movie catalogue (title, genres, poster);
    5. label the response with its source, so the frontend knows whether it is
       personalised.

    Raises RecommendationUnavailableError if the recommender this user needs is
    not loaded.
    """
    history = get_rating_history(db, user_id)

    if has_enough_history_for_cf(history):
        if recommenders.cf is None:
            raise RecommendationUnavailableError("collaborative filtering model not loaded")
        source = RecommendationSource.COLLABORATIVE_FILTERING
        scored = recommenders.cf(history, limit)
    else:
        if recommenders.popularity is None:
            raise RecommendationUnavailableError("popularity baseline not loaded")
        source = RecommendationSource.POPULARITY
        # The rated movies are removed BEFORE the top `limit` is taken, so the list
        # stays full when enough unrated movies remain.
        scored = recommenders.popularity(limit, exclude_movie_ids=set(history))

    # Safety net: the ML functions already exclude rated movies, but the rule
    # "never recommend a movie the user has rated" is enforced here as well, so it
    # does not depend only on code outside the backend. Watchlist movies are NOT
    # removed: wanting to watch a movie is a reason to keep recommending it.
    scored = _without_rated_movies(scored, history)

    # The catalogue helper keeps the order, drops unknown and repeated IDs and
    # numbers the remaining movies 1, 2, 3... (two queries in total, not one per movie).
    items = movie_service.build_recommended_movies(db, scored)[:limit]

    personalized = source is RecommendationSource.COLLABORATIVE_FILTERING
    return RecommendationResponse(
        source=source,
        personalized=personalized,
        message=None if personalized else COLD_START_MESSAGE,
        items=items,
    )


def _without_rated_movies(
    scored: Iterable[tuple[int, float]], history: Mapping[int, float]
) -> list[tuple[int, float]]:
    return [(movie_id, score) for movie_id, score in scored if movie_id not in history]
