"""Offline evaluation of the AuraCinema recommenders.

Two separate entry points, so the data each one may read is explicit:

* ``validate`` - configuration selection for item-based CF. Reads ONLY ``ratings_train.csv``,
  splits it chronologically per user into an internal training subset and a validation
  subset (same rule as Phase 2), trains temporary models on the internal subset and
  compares the candidate neighbour counts. ``ratings_test.csv`` is never opened.
* ``evaluate`` - final comparison of the trained CF model and the popularity baseline on
  ``ratings_test.csv``. It only LOADS the two fixed models (no training happens here) and
  reads the test file after both are loaded; test ratings are used only to decide which
  recommended movies are relevant.
* ``discovery`` - measurement of the three Discovery Mode settings (Phase 7.4) with the same
  fixed models and test relevance as ``evaluate``: relevance, novelty, intra-list diversity,
  coverage and overlap with the plain CF list. The mode weights are fixed in
  ``src/discovery_mode.py`` before this run; nothing is tuned here.

Protocol (agreed in Phase 4, §12.4): a held-out movie is relevant when its rating is
>= 3.5; K = 5, 10 and 20; candidates = catalogue movies the user has not rated in the
training data; metrics are computed per user and macro-averaged over the users with at
least one relevant held-out movie (the same users for both algorithms).

Usage (from the ``ml`` folder)::

    python -m src.evaluate_recommendations validate     # internal validation (training file only)
    python -m src.evaluate_recommendations evaluate     # final test-set comparison
    python -m src.evaluate_recommendations discovery    # Discovery Mode measurement
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.collaborative_filtering import (
    DEFAULT_OUTPUT_DIR as DEFAULT_MODEL_DIR,
)
from src.collaborative_filtering import (
    DEFAULT_PROCESSED_DIR,
    DEFAULT_VALIDATION_RESULTS,
    SCORING_METHODS,
    ItemCFModel,
    build_rating_matrix,
    fit_item_cf,
    load_cf_model,
    load_verified_training_inputs,
    recommend_for_history,
    truncate_neighbours,
    with_scoring,
)
from src.discovery_mode import CANDIDATE_POOL, DISCOVERY_WEIGHTS, rerank
from src.popularity_baseline import load_popularity_baseline, load_training_ratings, top_n_popular_movies
from src.prepare_data import OUTPUT_FILES as DATA_FILES
from src.prepare_data import DataValidationError, _json_default, sha256_of, split_ratings_by_user

RELEVANCE_THRESHOLD = 3.5
K_VALUES = (5, 10, 20)
VALIDATION_FRACTION = 0.2
CANDIDATE_NEIGHBOURS = (20, 50, 100)
PRIMARY_METRIC = ("ndcg", 10)
USER_BATCH = 2000
# Discovery Mode measurement: list length shown by the API by default, and a fixed-seed
# user sample (the greedy re-ranking runs in Python, once per user and mode).
DISCOVERY_K = 10
DISCOVERY_SAMPLE_USERS = 10_000
DISCOVERY_SEED = 42

DEFAULT_EVALUATION_DIR = DEFAULT_VALIDATION_RESULTS.parent
OUTPUT_FILES = {
    "validation": DEFAULT_VALIDATION_RESULTS.name,
    "evaluation": "offline_evaluation_results.json",
    "discovery": "discovery_mode_results.json",
}
RATING_COLUMNS = ["userId", "movieId", "rating", "timestamp"]

logger = logging.getLogger("evaluate_recommendations")


# ---------------------------------------------------------------------------
# 1. Metrics (binary relevance)
# ---------------------------------------------------------------------------


def ranking_metrics(recommended: Sequence[int], relevant: set[int], k: int) -> dict[str, float]:
    """Precision@K, Recall@K and NDCG@K of one user's ranked list.

    * Precision@K = hits in the first K / K. The denominator is always K, so a list
      shorter than K counts its missing positions as not relevant.
    * Recall@K = hits in the first K / number of relevant held-out movies.
    * NDCG@K = DCG / IDCG with gain 1 for a relevant movie and discount 1/log2(position+1);
      IDCG is the DCG of an ideal list with min(K, |relevant|) relevant movies first.

    Undefined for a user without relevant movies, so that case raises ValueError.
    """
    if not relevant:
        raise ValueError("metrics are undefined for a user without relevant movies")
    gains = [1.0 if movie_id in relevant else 0.0 for movie_id in list(recommended)[:k]]
    hits = sum(gains)
    dcg = sum(gain / math.log2(position + 2) for position, gain in enumerate(gains))
    idcg = sum(1.0 / math.log2(position + 2) for position in range(min(k, len(relevant))))
    return {"precision": hits / k, "recall": hits / len(relevant), "ndcg": dcg / idcg}


def macro_average(
    lists: dict[int, Sequence[int]], relevant: dict[int, set[int]], k_values: Iterable[int], n_catalogue: int
) -> dict[str, dict]:
    """Mean of each user's metrics over the users in ``relevant``, plus coverage.

    Every user in ``relevant`` must have a list (possibly empty). Coverage is reported as
    the share of users who received K movies and the share of the catalogue that appears
    in at least one top-K list.
    """
    users = sorted(relevant)
    missing = [user for user in users if user not in lists]
    if missing:
        raise ValueError(f"{len(missing)} evaluated user(s) have no recommendation list, e.g. {missing[:5]}")
    results = {}
    for k in k_values:
        per_user = [ranking_metrics(lists[user], relevant[user], k) for user in users]
        recommended = {movie_id for user in users for movie_id in list(lists[user])[:k]}
        results[f"@{k}"] = {
            **{name: float(np.mean([m[name] for m in per_user])) for name in ("precision", "recall", "ndcg")},
            "users": len(users),
            "users_with_full_list": round(float(np.mean([len(lists[user]) >= k for user in users])), 6),
            "catalogue_coverage": round(len(recommended) / n_catalogue, 6),
        }
    return results


def relevant_items(holdout: pd.DataFrame, threshold: float = RELEVANCE_THRESHOLD) -> tuple[dict[int, set[int]], dict]:
    """``{userId: relevant movieIds}`` of a held-out set, plus a description of the population.

    Users whose held-out ratings are all below the threshold are left out (and counted).
    """
    positive = holdout[holdout["rating"] >= threshold]
    relevant = {int(user): set(group.tolist()) for user, group in positive.groupby("userId")["movieId"]}
    n_users = int(holdout["userId"].nunique())
    population = {
        "relevance_rule": f"held-out rating >= {threshold}",
        "held_out_ratings": len(holdout),
        "held_out_users": n_users,
        "relevant_ratings": len(positive),
        "evaluated_users": len(relevant),
        "excluded_users_without_relevant_items": n_users - len(relevant),
        "relevant_items_per_evaluated_user": {
            "mean": round(float(positive.groupby("userId").size().mean()), 3) if relevant else 0.0,
            "median": float(positive.groupby("userId").size().median()) if relevant else 0.0,
        },
    }
    return relevant, population


# ---------------------------------------------------------------------------
# 2. Recommendation lists for many users (same candidate rules for both methods)
# ---------------------------------------------------------------------------


def cf_recommendation_lists(
    model: ItemCFModel, history: pd.DataFrame, index_map: pd.DataFrame, users: Sequence[int], n: int
) -> dict[int, list[int]]:
    """Top-``n`` CF movieIds for each user, from their ``history`` ratings only.

    Rated movies are excluded inside the scoring; candidates without similarity evidence
    are not filled in, so a list can be shorter than ``n``.
    """
    matrix, user_ids = build_rating_matrix(history, index_map)
    rows = np.searchsorted(user_ids, users)
    if len(users) and (rows.max() >= len(user_ids) or not np.array_equal(user_ids[rows], users)):
        raise DataValidationError("some evaluated users have no history ratings")
    lists = {}
    for start in range(0, len(users), USER_BATCH):
        batch = rows[start : start + USER_BATCH]
        for user, recommendations in zip(
            users[start : start + USER_BATCH], recommend_for_history(model, matrix[batch], n), strict=True
        ):
            lists[int(user)] = [movie_id for movie_id, _ in recommendations]
    return lists


def popularity_recommendation_lists(ranking: pd.DataFrame, history: pd.DataFrame, users: Sequence[int], n: int):
    """Top-``n`` popular movieIds per user, excluding the user's history (reuses Phase 4)."""
    ordered = history.sort_values("userId", kind="mergesort")
    user_ids, starts = np.unique(ordered["userId"].to_numpy(), return_index=True)
    rated = dict(zip(user_ids.tolist(), np.split(ordered["movieId"].to_numpy(), starts[1:]), strict=True))
    return {
        int(user): [movie_id for movie_id, _ in top_n_popular_movies(ranking, n, exclude_movie_ids=rated[int(user)])]
        for user in users
    }


def check_lists_respect_candidates(lists: dict[int, list[int]], history: pd.DataFrame, catalogue: set[int]) -> None:
    """No recommended movie may be outside the catalogue or already rated by the user."""
    recommended = pd.DataFrame(
        [(user, movie_id) for user, movie_ids in lists.items() for movie_id in movie_ids], columns=["userId", "movieId"]
    )
    if not recommended["movieId"].isin(catalogue).all():
        raise DataValidationError("a recommendation is outside the catalogue")
    if recommended.merge(history[["userId", "movieId"]], on=["userId", "movieId"]).shape[0]:
        raise DataValidationError("a recommendation is a movie the user already rated")


# ---------------------------------------------------------------------------
# 3. Internal validation (training file only)
# ---------------------------------------------------------------------------


def split_for_validation(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological per-user split of the TRAINING ratings (Phase 2 rule reused).

    For each user, ordered by (timestamp, movieId), the latest floor(20%) ratings (at
    least one) form the validation subset and the earlier ones the internal training subset.
    """
    internal, validation, _ = split_ratings_by_user(train, VALIDATION_FRACTION, min_user_ratings=1)
    return internal[RATING_COLUMNS], validation[RATING_COLUMNS]


def select_configuration(results: dict[str, dict]) -> str:
    """Highest NDCG@10; on an exact tie the smaller (cheaper) neighbour count."""
    name, k = PRIMARY_METRIC
    return max(results, key=lambda key: (results[key]["metrics"][f"@{k}"][name], -results[key]["neighbours"]))


def run_cf_validation(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_EVALUATION_DIR,
    candidates: Sequence[int] = CANDIDATE_NEIGHBOURS,
    overwrite: bool = False,
    scorings: Sequence[str] = SCORING_METHODS,
) -> dict:
    """Compare neighbour counts x scoring rules on the internal validation split."""
    output_path = Path(output_dir) / OUTPUT_FILES["validation"]
    _refuse_to_overwrite(output_path, overwrite)
    started = time.perf_counter()
    train, index_map, source = load_verified_training_inputs(processed_dir)
    internal, validation = split_for_validation(train)
    del train
    relevant, population = relevant_items(validation)
    users = np.array(sorted(relevant), dtype="int64")
    logger.info("Internal split: %d training / %d validation ratings", len(internal), len(validation))

    fit_started = time.perf_counter()
    largest, model_stats = fit_item_cf(internal, index_map, max(candidates))
    fit_seconds = time.perf_counter() - fit_started
    results = {}
    for k in sorted(candidates):
        truncated = largest if k == largest.n_neighbours else truncate_neighbours(largest, k)
        for scoring in scorings:
            step = time.perf_counter()
            model = with_scoring(truncated, scoring)
            lists = cf_recommendation_lists(model, internal, index_map, users, max(K_VALUES))
            key = f"{scoring}/k={k}"
            results[key] = {
                "scoring": scoring,
                "neighbours": k,
                "metrics": macro_average(lists, relevant, K_VALUES, len(index_map)),
                "stored_similarities": int(model.neighbours.nnz),
                "recommendation_seconds": round(time.perf_counter() - step, 1),
            }
            logger.info("%s: %s", key, _format_metrics(results[key]["metrics"]))
    selected = select_configuration(results)

    output = {
        "purpose": "selection of the CF neighbour count; ratings_test.csv not used",
        "source": source,
        "split": {
            "method": "chronological per user on ratings_train.csv; order (timestamp, movieId); latest "
            f"floor(n * {VALIDATION_FRACTION}) (min 1) ratings per user to validation",
            "internal_training_ratings": len(internal),
            "validation_ratings": len(validation),
            "users": int(internal["userId"].nunique()),
            "internal_training_ratings_per_user_min": int(internal.groupby("userId").size().min()),
        },
        "population": population,
        "k_values": list(K_VALUES),
        "selection_rule": f"highest {PRIMARY_METRIC[0]}@{PRIMARY_METRIC[1]}; exact tie -> fewer neighbours",
        "scoring_rules": {
            "weighted_sum": "sum(sim(j,i) * (r_ui - mean_u)) over rated neighbours of j",
            "weighted_average": "mean_u + sum(sim * (r_ui - mean_u)) / sum(|sim|) (formula of the project brief)",
        },
        "similarity_seconds_for_largest_k": round(fit_seconds, 1),
        "internal_model_counts": model_stats,
        "results": results,
        "selected_configuration": selected,
        "selected_scoring": results[selected]["scoring"],
        "selected_neighbours": results[selected]["neighbours"],
        "run": {
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "total_seconds": round(time.perf_counter() - started, 1),
        },
    }
    _write_json(output, output_path)
    logger.info("Selected %s (by %s@%d)", selected, *PRIMARY_METRIC)
    return output


# ---------------------------------------------------------------------------
# 4. Final offline evaluation (the only code that reads ratings_test.csv)
# ---------------------------------------------------------------------------


def compare(cf: dict, popularity: dict) -> dict:
    """Absolute and relative differences (CF - popularity) per K and metric."""
    comparison = {}
    for at, cf_metrics in cf.items():
        comparison[at] = {}
        for name in ("precision", "recall", "ndcg"):
            a, b = cf_metrics[name], popularity[at][name]
            comparison[at][name] = {
                "cf": a,
                "popularity": b,
                "absolute_difference": a - b,
                "relative_change_percent": (a - b) / b * 100 if b > 0 else None,
            }
    return comparison


def run_offline_evaluation(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_dir: Path = DEFAULT_EVALUATION_DIR,
    overwrite: bool = False,
) -> dict:
    """Evaluate the fixed CF model and popularity baseline on the original test set."""
    output_path = Path(output_dir) / OUTPUT_FILES["evaluation"]
    _refuse_to_overwrite(output_path, overwrite)
    started = time.perf_counter()

    # 1-2. Fixed models, training history and test relevance (no training happens here).
    fixed = _load_fixed_models_and_test_relevance(Path(processed_dir), model_dir)
    train, index_map, source = fixed["train"], fixed["index_map"], fixed["source"]
    cf_model, cf_manifest = fixed["cf_model"], fixed["cf_manifest"]
    ranking, popularity_manifest = fixed["ranking"], fixed["popularity_manifest"]
    relevant, population = fixed["relevant"], fixed["population"]
    users = np.array(sorted(relevant), dtype="int64")

    # 3. Both methods, same users, same candidates (catalogue minus the user's training movies).
    timings = {}
    step = time.perf_counter()
    cf_lists = cf_recommendation_lists(cf_model, train, index_map, users, max(K_VALUES))
    timings["cf_recommendation_seconds"] = round(time.perf_counter() - step, 1)
    step = time.perf_counter()
    popularity_lists = popularity_recommendation_lists(ranking, train, users, max(K_VALUES))
    timings["popularity_recommendation_seconds"] = round(time.perf_counter() - step, 1)
    catalogue = set(index_map["movieId"].tolist())
    for lists in (cf_lists, popularity_lists):
        check_lists_respect_candidates(lists, train, catalogue)

    cf_results = macro_average(cf_lists, relevant, K_VALUES, len(catalogue))
    popularity_results = macro_average(popularity_lists, relevant, K_VALUES, len(catalogue))
    output = {
        "purpose": "final offline evaluation on ratings_test.csv; models fixed before this run",
        "source": {
            **source,
            "test_file": DATA_FILES["test"],
            "test_file_sha256": fixed["test_sha256"],
            "cf_model_content_sha256": cf_manifest["output"]["content_sha256"],
            "cf_neighbours": cf_model.n_neighbours,
            "cf_scoring": cf_model.scoring,
            "popularity_baseline_sha256": popularity_manifest["output"]["sha256"],
        },
        "protocol": {
            "candidates": "catalogue movies not rated by the user in ratings_train.csv (watchlist not simulated)",
            "k_values": list(K_VALUES),
            "averaging": "macro (mean of per-user values) over the same users for both algorithms",
            "short_lists": "precision denominator is always K; CF lists are not filled with other methods",
        },
        "population": population,
        "results": {"item_based_cf": cf_results, "popularity": popularity_results},
        "comparison": compare(cf_results, popularity_results),
        "run": {
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            **timings,
            "total_seconds": round(time.perf_counter() - started, 1),
        },
    }
    _write_json(output, output_path)
    for name, results in output["results"].items():
        logger.info("%s: %s", name, _format_metrics(results))
    return output


def _load_fixed_models_and_test_relevance(processed_dir: Path, model_dir: Path) -> dict:
    """Load the two fixed models, the verified training history and the test relevance.

    Shared by ``evaluate`` and ``discovery``. No training happens here; the test file is
    read only after both models are loaded and is used only to decide relevance.
    """
    # 1. Fixed models and training history.
    train, index_map, source = load_verified_training_inputs(processed_dir)
    cf_model, cf_manifest = load_cf_model(model_dir, processed_dir)
    ranking, popularity_manifest = load_popularity_baseline(model_dir)
    trained_on = {cf_manifest["source"]["training_file_sha256"], popularity_manifest["source"]["training_file_sha256"]}
    if trained_on != {source["training_file_sha256"]}:
        raise DataValidationError("both models must be trained on the current ratings_train.csv; retrain them")

    # 2. Test ratings: read only now, used only to define relevance.
    dataset = json.loads((processed_dir / DATA_FILES["manifest"]).read_text(encoding="utf-8"))
    test_path = processed_dir / DATA_FILES["test"]
    if sha256_of(test_path) != dataset["outputs"]["test"]["sha256"]:
        raise DataValidationError(f"{test_path.name} does not match the SHA-256 in {DATA_FILES['manifest']}")
    test = load_training_ratings(test_path)  # same structural validation as the training file
    relevant, population = relevant_items(test)
    return {
        "train": train,
        "index_map": index_map,
        "source": source,
        "cf_model": cf_model,
        "cf_manifest": cf_manifest,
        "ranking": ranking,
        "popularity_manifest": popularity_manifest,
        "relevant": relevant,
        "population": population,
        "test_sha256": dataset["outputs"]["test"]["sha256"],
    }


# ---------------------------------------------------------------------------
# 5. Discovery Mode measurement (Phase 7.4)
# ---------------------------------------------------------------------------


def intra_list_diversity(movie_ids: Sequence[int], genres: dict[int, set[str]]) -> float:
    """Mean genre Jaccard DISTANCE over all pairs of a list (Ziegler et al., 2005).

    1 = no two movies share a genre; 0 = all movies have the same genres. Two movies
    without genres count as distance 1. Undefined (NaN) for lists shorter than 2.
    """
    distances = []
    for position, first in enumerate(movie_ids):
        for second in movie_ids[position + 1 :]:
            a, b = genres.get(first, set()), genres.get(second, set())
            union = len(a | b)
            distances.append(1.0 - (len(a & b) / union if union else 0.0))
    return float(np.mean(distances)) if distances else math.nan


def mean_self_information(movie_ids: Sequence[int], rating_counts: dict[int, int], n_users: int) -> float:
    """Mean novelty of a list in bits: ``-log2(raters(i) / users)`` (Zhou et al., 2010).

    ``raters(i)`` is the movie's number of training ratings (one per user and movie).
    """
    if not movie_ids:
        return math.nan
    return float(np.mean([-math.log2(max(rating_counts.get(movie, 1), 1) / n_users) for movie in movie_ids]))


def load_catalogue_genres(processed_dir: Path) -> dict[int, set[str]]:
    """``{movieId: genres}`` from ``movies_catalogue.csv``; "(no genres listed)" = no genres.

    The backend reads the same genres from PostgreSQL (``Movie.genre_list``).
    """
    catalogue = pd.read_csv(Path(processed_dir) / DATA_FILES["catalogue"], usecols=["movieId", "genres"])
    return {
        int(movie_id): set() if text == "(no genres listed)" else set(str(text).split("|"))
        for movie_id, text in zip(catalogue["movieId"], catalogue["genres"], strict=True)
    }


def run_discovery_evaluation(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    model_dir: Path = DEFAULT_MODEL_DIR,
    output_dir: Path = DEFAULT_EVALUATION_DIR,
    overwrite: bool = False,
    sample_users: int = DISCOVERY_SAMPLE_USERS,
) -> dict:
    """Measure the Discovery Mode settings against the plain CF list (and popularity).

    For a fixed-seed sample of the evaluated test users, the CF model produces its top
    ``CANDIDATE_POOL`` candidates from the user's training ratings (as the API does), and
    each mode re-ranks them with ``discovery_mode.rerank``. Every list has ``DISCOVERY_K``
    movies and is measured on: Precision/Recall/NDCG@K (test relevance), novelty (mean
    self-information), intra-list genre diversity, catalogue coverage, and the share of
    the plain CF top-K that the list keeps. A paired 95% interval of the NDCG@K difference
    with plain CF tells whether a relevance drop is distinguishable from sampling noise.
    """
    output_path = Path(output_dir) / OUTPUT_FILES["discovery"]
    _refuse_to_overwrite(output_path, overwrite)
    started = time.perf_counter()
    processed_dir = Path(processed_dir)

    fixed = _load_fixed_models_and_test_relevance(processed_dir, model_dir)
    train, index_map, ranking = fixed["train"], fixed["index_map"], fixed["ranking"]
    everyone = np.array(sorted(fixed["relevant"]), dtype="int64")
    rng = np.random.default_rng(DISCOVERY_SEED)
    users = np.sort(rng.choice(everyone, size=min(sample_users, len(everyone)), replace=False))
    relevant = {int(user): fixed["relevant"][int(user)] for user in users}
    history = train[train["userId"].isin(users)]

    genres = load_catalogue_genres(processed_dir)
    rating_counts = dict(zip(ranking["movieId"].tolist(), ranking["rating_count"].tolist(), strict=True))
    n_users = int(train["userId"].nunique())

    # Candidates: the CF top-CANDIDATE_POOL of each user, as requested by the API. Only
    # the order matters to the re-ranking, so a rank-based placeholder score is passed.
    step = time.perf_counter()
    candidates = cf_recommendation_lists(fixed["cf_model"], history, index_map, users, CANDIDATE_POOL)
    lists = {"item_based_cf": {user: ids[:DISCOVERY_K] for user, ids in candidates.items()}}
    for mode in DISCOVERY_WEIGHTS:
        lists[mode] = {}
        for user, ids in candidates.items():
            ranked = [(movie_id, -float(rank)) for rank, movie_id in enumerate(ids)]
            reranked = rerank(ranked, DISCOVERY_K, mode, genres, rating_counts)
            lists[mode][user] = [movie_id for movie_id, _ in reranked]
    lists["popularity"] = popularity_recommendation_lists(ranking, history, users, DISCOVERY_K)
    recommendation_seconds = round(time.perf_counter() - step, 1)

    catalogue = set(index_map["movieId"].tolist())
    plain = lists["item_based_cf"]

    def per_user_ndcg(method_lists):
        return np.array([ranking_metrics(method_lists[user], relevant[user], DISCOVERY_K)["ndcg"] for user in relevant])

    plain_ndcg = per_user_ndcg(plain)
    results = {}
    for method, method_lists in lists.items():
        check_lists_respect_candidates(method_lists, history, catalogue)
        metrics = macro_average(method_lists, relevant, (DISCOVERY_K,), len(catalogue))[f"@{DISCOVERY_K}"]
        difference = per_user_ndcg(method_lists) - plain_ndcg
        margin = 1.96 * float(difference.std(ddof=1)) / math.sqrt(len(difference)) if len(difference) > 1 else 0.0
        results[method] = {
            **metrics,
            "novelty_bits": float(
                np.nanmean([mean_self_information(method_lists[user], rating_counts, n_users) for user in relevant])
            ),
            "intra_list_diversity": float(
                np.nanmean([intra_list_diversity(method_lists[user], genres) for user in relevant])
            ),
            "overlap_with_cf": float(
                np.mean(
                    [
                        len(set(method_lists[user]) & set(plain[user])) / len(plain[user])
                        for user in relevant
                        if plain[user]
                    ]
                )
            ),
            "ndcg_difference_vs_cf": {
                "mean": float(difference.mean()),
                "ci95_low": float(difference.mean()) - margin,
                "ci95_high": float(difference.mean()) + margin,
            },
        }
        logger.info(
            "%s: NDCG@%d=%.4f novelty=%.2f ILD=%.3f overlap=%.2f",
            method,
            DISCOVERY_K,
            results[method]["ndcg"],
            results[method]["novelty_bits"],
            results[method]["intra_list_diversity"],
            results[method]["overlap_with_cf"],
        )

    output = {
        "purpose": "measurement of the Discovery Mode settings on ratings_test.csv; weights fixed before this run",
        "source": {
            **fixed["source"],
            "test_file": DATA_FILES["test"],
            "test_file_sha256": fixed["test_sha256"],
            "cf_model_content_sha256": fixed["cf_manifest"]["output"]["content_sha256"],
            "popularity_baseline_sha256": fixed["popularity_manifest"]["output"]["sha256"],
        },
        "protocol": {
            "k": DISCOVERY_K,
            "candidate_pool": CANDIDATE_POOL,
            "mode_weights": DISCOVERY_WEIGHTS,
            "users": f"{len(users)} of {len(everyone)} evaluated test users, sampled with seed {DISCOVERY_SEED}",
            "relevance": fixed["population"]["relevance_rule"],
            "novelty": "mean -log2(training raters / training users) of the list, in bits",
            "intra_list_diversity": "mean pairwise genre Jaccard distance within the list",
            "overlap_with_cf": "share of the plain CF top-K movies also in the list (users with a CF list)",
            "ndcg_difference_vs_cf": "paired per-user difference, normal-approximation 95% interval",
        },
        "results": results,
        "run": {
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "recommendation_seconds": recommendation_seconds,
            "total_seconds": round(time.perf_counter() - started, 1),
        },
    }
    _write_json(output, output_path)
    return output


# ---------------------------------------------------------------------------
# 6. Helpers and command line
# ---------------------------------------------------------------------------


def _refuse_to_overwrite(path: Path, overwrite: bool) -> None:
    if Path(path).exists() and not overwrite:
        raise FileExistsError(f"Output file already exists: '{path}'. Use --overwrite to replace it.")


def _write_json(content: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, default=_json_default)


def _format_metrics(metrics: dict) -> str:
    return "; ".join(
        f"{at} P={m['precision']:.4f} R={m['recall']:.4f} NDCG={m['ndcg']:.4f}" for at, m in metrics.items()
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline evaluation of the AuraCinema recommenders.")
    parser.add_argument("command", choices=["validate", "evaluate", "discovery"])
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_EVALUATION_DIR)
    parser.add_argument("--overwrite", action="store_true", help="replace the results of a previous run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    try:
        if args.command == "validate":
            run_cf_validation(args.processed_dir, args.output_dir, overwrite=args.overwrite)
        elif args.command == "evaluate":
            run_offline_evaluation(args.processed_dir, args.model_dir, args.output_dir, overwrite=args.overwrite)
        else:
            run_discovery_evaluation(args.processed_dir, args.model_dir, args.output_dir, overwrite=args.overwrite)
    except (FileNotFoundError, FileExistsError, DataValidationError) as error:
        logger.error("%s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
