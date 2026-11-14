"""Popularity baseline for the AuraCinema recommendation engine.

The baseline ranks the movies of the catalogue by how many TRAINING ratings they
received. It is non-personalised: every user receives the same ranking (minus the
movies they have already rated). It is the benchmark against which the item-based
collaborative filtering model will later be compared.

Method (see the Project Report or ml/docs/popularity_baseline_implementation.md for the justification):

* ``popularity_score = rating_count`` = number of ratings of the movie in ``ratings_train.csv``;
* ranking: ``rating_count`` descending, then ``movieId`` ascending (deterministic tie-break);
* ``average_rating`` (mean training rating) is stored as complementary information only
  and never influences the ranking.

Only ``ratings_train.csv`` and ``movies_catalogue.csv`` are read. ``ratings_test.csv`` is
never opened, so test ratings cannot influence the baseline. The internal ``item_index``
of ``movie_index_map.csv`` is not used: every output is keyed by the MovieLens ``movieId``.

Outputs (written to ``ml/data/models/`` by default):

* ``popularity_baseline.csv`` - one row per catalogue movie:
  ``rank, movieId, popularity_score, rating_count, average_rating``;
* ``popularity_baseline_manifest.json`` - method, source files and their hashes, counts,
  distribution statistics, validation results and the hash of the CSV.

Usage (from the ``ml`` folder)::

    python -m src.popularity_baseline            # refuses to replace existing outputs
    python -m src.popularity_baseline --overwrite
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Reused from the data-preparation pipeline instead of being duplicated.
from src.prepare_data import OUTPUT_FILES as DATA_FILES
from src.prepare_data import (
    VALID_RATINGS,
    DataValidationError,
    _json_default,
    compute_training_movie_stats,
    sha256_of,
)

BASELINE_VERSION = "1.0.0"
ALGORITHM = "raw_training_rating_count"

ML_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = ML_ROOT / "data" / "processed"
DEFAULT_OUTPUT_DIR = ML_ROOT / "data" / "models"

OUTPUT_FILES = {
    "ranking": "popularity_baseline.csv",
    "manifest": "popularity_baseline_manifest.json",
}

TRAINING_COLUMNS = ["userId", "movieId", "rating", "timestamp"]
TRAINING_DTYPES = {"userId": "int32", "movieId": "int32", "rating": "float64", "timestamp": "int64"}
CATALOGUE_COLUMNS = ["movieId", "title", "genres", "imdbId", "tmdbId"]
RANKING_COLUMNS = ["rank", "movieId", "popularity_score", "rating_count", "average_rating"]

MIN_RATING, MAX_RATING = min(VALID_RATINGS), max(VALID_RATINGS)

logger = logging.getLogger("popularity_baseline")


# ---------------------------------------------------------------------------
# 1. Loading and validating the inputs
# ---------------------------------------------------------------------------


def _check_columns(actual: Iterable[str], expected: list[str], name: str) -> None:
    """Structural check: the file must have exactly the expected columns (in any order)."""
    actual = list(actual)
    missing = [col for col in expected if col not in actual]
    unexpected = [col for col in actual if col not in expected]
    if missing or unexpected:
        raise DataValidationError(
            f"{name}: unexpected structure (missing columns: {missing or 'none'}; "
            f"unexpected columns: {unexpected or 'none'})"
        )


def _require_file(path: Path) -> Path:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Required file not found: '{path}'")
    return path


def load_training_ratings(path: Path) -> pd.DataFrame:
    """Read ``ratings_train.csv`` with compact numeric types and validate it.

    Missing values or non-numeric text make the typed read fail; this is reported as a
    DataValidationError instead of being repaired.
    """
    path = _require_file(path)
    _check_columns(pd.read_csv(path, nrows=0).columns, TRAINING_COLUMNS, path.name)
    try:
        train = pd.read_csv(path, dtype=TRAINING_DTYPES)
    except (ValueError, TypeError) as error:
        raise DataValidationError(f"{path.name} contains missing or non-numeric values: {error}") from error
    validate_training_ratings(train)
    return train


def validate_training_ratings(train: pd.DataFrame) -> None:
    """Fail clearly if the training ratings cannot give a reliable popularity count.

    Checks: exact columns, at least one rating, numeric non-boolean columns, no missing
    values, positive integer IDs and timestamps, ratings on the MovieLens half-star scale
    (which also rejects NaN and infinity) and no duplicated ``(userId, movieId)`` pair,
    because a duplicate would count the same user twice for one movie.
    """
    _check_columns(train.columns, TRAINING_COLUMNS, "training ratings")
    if train.empty:
        raise DataValidationError("training ratings: the table is empty")
    for col in TRAINING_COLUMNS:
        if not pd.api.types.is_numeric_dtype(train[col]) or pd.api.types.is_bool_dtype(train[col]):
            raise DataValidationError(f"training ratings: column '{col}' must be numeric, got {train[col].dtype}")
    if train[TRAINING_COLUMNS].isna().any().any():
        raise DataValidationError("training ratings: missing values found")

    problems = []
    for col in ["userId", "movieId", "timestamp"]:
        values = train[col]
        if ((values <= 0) | (values % 1 != 0)).any():
            problems.append(f"'{col}' must contain positive integers")
    invalid_ratings = ~train["rating"].isin(VALID_RATINGS)
    if invalid_ratings.any():
        examples = sorted(train.loc[invalid_ratings, "rating"].unique().tolist())[:5]
        problems.append(f"{int(invalid_ratings.sum())} rating(s) outside 0.5-5.0 in half-star steps, e.g. {examples}")
    if train.duplicated(["userId", "movieId"]).any():
        problems.append("duplicated (userId, movieId) pairs")
    if problems:
        raise DataValidationError("training ratings: " + "; ".join(problems))


def load_catalogue_movie_ids(path: Path) -> pd.Series:
    """Read the movie IDs of ``movies_catalogue.csv`` (the universe of the baseline)."""
    path = _require_file(path)
    catalogue = pd.read_csv(path)
    _check_columns(catalogue.columns, CATALOGUE_COLUMNS, path.name)
    movie_ids = catalogue["movieId"]
    validate_catalogue_movie_ids(movie_ids)
    return movie_ids.astype("int64")


def validate_catalogue_movie_ids(movie_ids: pd.Series) -> None:
    """Catalogue IDs must be present, positive integers and unique."""
    if len(movie_ids) == 0:
        raise DataValidationError("catalogue: no movies")
    if not pd.api.types.is_numeric_dtype(movie_ids) or movie_ids.isna().any():
        raise DataValidationError("catalogue: movieId must be present and numeric for every movie")
    if ((movie_ids <= 0) | (movie_ids % 1 != 0)).any():
        raise DataValidationError("catalogue: movieId must be a positive integer")
    if movie_ids.duplicated().any():
        duplicates = sorted(movie_ids[movie_ids.duplicated()].unique().tolist())[:10]
        raise DataValidationError(f"catalogue: duplicated movieId values {duplicates}")


# ---------------------------------------------------------------------------
# 2. Popularity statistics and ranking
# ---------------------------------------------------------------------------


def compute_movie_statistics(train: pd.DataFrame, catalogue_movie_ids: Iterable[int]) -> pd.DataFrame:
    """Per-movie ``rating_count`` and ``average_rating`` from TRAINING ratings only.

    Reuses ``compute_training_movie_stats`` from the data-preparation pipeline. The
    training movies must be exactly the catalogue movies: a catalogue movie without
    training ratings, or a training movie outside the catalogue, stops the calculation
    (nothing is dropped or filled in silently).
    """
    validate_training_ratings(train)
    catalogue_ids = pd.Series(list(catalogue_movie_ids))
    validate_catalogue_movie_ids(catalogue_ids)

    catalogue_set = set(catalogue_ids.astype("int64").tolist())
    training_set = set(train["movieId"].astype("int64").unique().tolist())
    without_ratings = sorted(catalogue_set - training_set)
    unknown = sorted(training_set - catalogue_set)
    if without_ratings:
        raise DataValidationError(
            f"{len(without_ratings)} catalogue movie(s) have no training rating, e.g. {without_ratings[:10]}"
        )
    if unknown:
        raise DataValidationError(f"{len(unknown)} training movie(s) are not in the catalogue, e.g. {unknown[:10]}")

    stats = compute_training_movie_stats(train).rename(
        columns={"train_rating_count": "rating_count", "train_mean_rating": "average_rating"}
    )
    return stats.astype({"movieId": "int64", "rating_count": "int64", "average_rating": "float64"}).reset_index(
        drop=True
    )


def rank_movies_by_popularity(stats: pd.DataFrame) -> pd.DataFrame:
    """Rank movies by ``rating_count`` (descending), ties broken by smaller ``movieId``.

    ``popularity_score`` is the raw training rating count, without transformation, so
    the score has a direct meaning ("number of training ratings"). Ranks are 1..N and
    unique, because the pair (rating_count, movieId) is unique for every movie.
    """
    _check_columns(stats.columns, ["movieId", "rating_count", "average_rating"], "movie statistics")
    ranked = stats.sort_values(["rating_count", "movieId"], ascending=[False, True], kind="mergesort")
    ranked = ranked.reset_index(drop=True)
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1, dtype="int64"))
    ranked["popularity_score"] = ranked["rating_count"].astype("int64")
    return ranked[RANKING_COLUMNS]


def build_popularity_ranking(train: pd.DataFrame, catalogue_movie_ids: Iterable[int]) -> pd.DataFrame:
    """Statistics + ranking + validation in one call. Raises if any check fails."""
    catalogue_movie_ids = list(catalogue_movie_ids)
    ranking = rank_movies_by_popularity(compute_movie_statistics(train, catalogue_movie_ids))
    checks = validate_popularity_ranking(ranking, catalogue_movie_ids, expected_total_ratings=len(train))
    _raise_if_failed(checks, "popularity ranking")
    return ranking


# ---------------------------------------------------------------------------
# 3. Validation of a ranking (freshly computed or loaded from disk)
# ---------------------------------------------------------------------------


def validate_popularity_ranking(
    ranking: pd.DataFrame,
    catalogue_movie_ids: Iterable[int] | None = None,
    expected_total_ratings: int | None = None,
) -> dict[str, bool]:
    """Consistency checks of a ranking. Returns check name -> passed.

    A missing column is a structural problem and raises immediately; the remaining
    checks are returned so that every failure can be reported at once.
    """
    _check_columns(ranking.columns, RANKING_COLUMNS, "popularity ranking")
    numeric = all(
        pd.api.types.is_numeric_dtype(ranking[col]) and not pd.api.types.is_bool_dtype(ranking[col])
        for col in RANKING_COLUMNS
    )
    if not numeric or ranking.empty:
        return {"non_empty_and_numeric": False}

    values = ranking[RANKING_COLUMNS].to_numpy(dtype="float64")
    counts = ranking["rating_count"]
    averages = ranking["average_rating"]
    expected_order = ranking.sort_values(["rating_count", "movieId"], ascending=[False, True], kind="mergesort")

    checks = {
        "non_empty_and_numeric": True,
        "no_missing_or_non_finite_values": bool(np.isfinite(values).all()),
        "movie_ids_positive_integers": bool(((ranking["movieId"] > 0) & (ranking["movieId"] % 1 == 0)).all()),
        "movie_ids_unique": bool(ranking["movieId"].is_unique),
        "ranks_are_1_to_n_without_duplicates": bool(
            (ranking["rank"].to_numpy() == np.arange(1, len(ranking) + 1)).all()
        ),
        "rating_counts_positive_integers": bool(((counts >= 1) & (counts % 1 == 0)).all()),
        "popularity_score_equals_rating_count": bool((ranking["popularity_score"] == counts).all()),
        "average_rating_within_scale": bool(((averages >= MIN_RATING) & (averages <= MAX_RATING)).all()),
        "order_is_count_desc_then_movie_id_asc": bool(
            (expected_order.index.to_numpy() == ranking.index.to_numpy()).all()
        ),
    }
    if catalogue_movie_ids is not None:
        catalogue_set = {int(movie_id) for movie_id in catalogue_movie_ids}
        checks["movies_match_catalogue_exactly"] = set(ranking["movieId"].astype("int64").tolist()) == catalogue_set
    if expected_total_ratings is not None:
        checks["rating_counts_sum_to_training_ratings"] = int(counts.sum()) == int(expected_total_ratings)
    return checks


def _raise_if_failed(checks: dict[str, bool], what: str) -> None:
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise DataValidationError(f"{what} failed validation checks: {failed}")


# ---------------------------------------------------------------------------
# 4. Descriptive statistics (stored in the manifest and used by the report)
# ---------------------------------------------------------------------------


def describe_popularity_distribution(ranking: pd.DataFrame) -> dict:
    """Distribution of rating counts and average ratings over the ranked movies.

    Everything here is derived from the training-only ranking. The thresholds are
    descriptive reference points; no movie is excluded because of them.
    """
    counts = ranking["rating_count"].astype("float64")
    averages = ranking["average_rating"]
    sorted_counts = np.sort(counts.to_numpy())[::-1]
    total = float(sorted_counts.sum())
    cumulative_share = np.cumsum(sorted_counts) / total
    n_movies = len(ranking)
    percentile_points = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]

    def percentiles(series: pd.Series, digits: int) -> dict:
        return {f"p{round(q * 100)}": round(float(v), digits) for q, v in series.quantile(percentile_points).items()}

    def ranks(series: pd.Series) -> pd.Series:
        return series.rank(method="average")

    # Rating-weighted global mean = mean of all training ratings (the "C" of a Bayesian average).
    global_mean = float((ranking["average_rating"] * counts).sum() / total)
    return {
        "movies": n_movies,
        "training_ratings": int(total),
        "rating_count": {
            "min": int(counts.min()),
            "max": int(counts.max()),
            "mean": round(float(counts.mean()), 2),
            "median": float(counts.median()),
            "std": round(float(counts.std()), 2),
            "coefficient_of_variation": round(float(counts.std() / counts.mean()), 4),
            "skewness": round(float(counts.skew()), 4),
            "percentiles": percentiles(counts, 1),
            "movies_below_threshold": {
                str(t): {"movies": int((counts < t).sum()), "share": round(float((counts < t).mean()), 4)}
                for t in [200, 500, 1000, 2000, 5000, 10000]
            },
        },
        "concentration": {
            "share_of_ratings_in_top_n": {
                str(n): round(float(cumulative_share[min(n, n_movies) - 1]), 4) for n in [10, 50, 100, 500, 1000]
            },
            "movies_needed_for_share": {
                str(share): int(np.searchsorted(cumulative_share, share - 1e-12) + 1) for share in [0.5, 0.8, 0.9]
            },
            "gini_coefficient": round(_gini(sorted_counts), 4),
        },
        "average_rating": {
            "global_mean_of_training_ratings": round(global_mean, 4),
            "min": round(float(averages.min()), 4),
            "max": round(float(averages.max()), 4),
            "mean_of_movie_averages": round(float(averages.mean()), 4),
            "median": round(float(averages.median()), 4),
            "std": round(float(averages.std()), 4),
            "skewness": round(float(averages.skew()), 4),
            "percentiles": percentiles(averages, 4),
        },
        "count_vs_average_rating": {
            "pearson": round(float(counts.corr(averages)), 4),
            "pearson_log10_count": round(float(np.log10(counts).corr(averages)), 4),
            # Spearman = Pearson correlation of the ranks (computed directly, no SciPy needed).
            "spearman": round(float(ranks(counts).corr(ranks(averages))), 4),
        },
    }


def _gini(values: np.ndarray) -> float:
    """Gini coefficient of non-negative values (0 = equal counts, close to 1 = concentrated)."""
    ordered = np.sort(np.asarray(values, dtype="float64"))
    n = len(ordered)
    if n == 0 or ordered.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * (index * ordered).sum()) / (n * ordered.sum()) - (n + 1) / n)


# ---------------------------------------------------------------------------
# 5. Persistence
# ---------------------------------------------------------------------------


def _refuse_to_overwrite(output_dir: Path, overwrite: bool) -> None:
    existing = [str(Path(output_dir) / name) for name in OUTPUT_FILES.values() if (Path(output_dir) / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Output file(s) already exist: {existing}. Use --overwrite to replace them.")


def write_popularity_baseline(ranking: pd.DataFrame, manifest: dict, output_dir: Path, overwrite: bool = False) -> dict:
    """Write the ranking CSV and its manifest (with the SHA-256 of the CSV).

    Existing outputs are replaced only when ``overwrite`` is True, as in the
    data-preparation pipeline, so a previous baseline is never replaced by accident.
    """
    output_dir = Path(output_dir)
    _refuse_to_overwrite(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / OUTPUT_FILES["ranking"]
    # Floats are written at full precision, so loading the file gives back the same values.
    ranking[RANKING_COLUMNS].to_csv(csv_path, index=False, lineterminator="\n")
    manifest = {
        **manifest,
        "output": {
            "file": csv_path.name,
            "rows": len(ranking),
            "columns": RANKING_COLUMNS,
            "sha256": sha256_of(csv_path),
        },
    }
    with open(output_dir / OUTPUT_FILES["manifest"], "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, default=_json_default)
    return manifest


def load_popularity_baseline(output_dir: Path = DEFAULT_OUTPUT_DIR) -> tuple[pd.DataFrame, dict]:
    """Load a previously generated baseline without recomputing any statistic.

    The CSV must match the hash recorded in the manifest, and the ranking is validated
    again, so a missing, edited, truncated or malformed file is reported, never used.
    Returns ``(ranking, manifest)``.
    """
    output_dir = Path(output_dir)
    manifest_path = output_dir / OUTPUT_FILES["manifest"]
    csv_path = output_dir / OUTPUT_FILES["ranking"]
    for path in (manifest_path, csv_path):
        if not path.is_file():
            raise FileNotFoundError(
                f"Popularity baseline file not found: '{path}'. Generate it with: python -m src.popularity_baseline"
            )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_hash = manifest["output"]["sha256"]
        expected_rows = int(manifest["output"]["rows"])
        algorithm = manifest["baseline"]["algorithm"]
        expected_total = int(manifest["counts"]["training_ratings"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise DataValidationError(f"{manifest_path.name} is malformed: {error!r}") from error
    if algorithm != ALGORITHM:
        raise DataValidationError(f"{manifest_path.name}: unsupported algorithm '{algorithm}'")
    if sha256_of(csv_path) != expected_hash:
        raise DataValidationError(
            f"{csv_path.name} does not match the hash in {manifest_path.name}; the file was changed after it "
            "was generated. Regenerate it with --overwrite."
        )

    try:
        # "round_trip" parses floats exactly as written; the default fast parser can
        # change the last binary digit of an average (found by the persistence test).
        ranking = pd.read_csv(csv_path, float_precision="round_trip")
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as error:
        raise DataValidationError(f"{csv_path.name} could not be parsed: {error}") from error
    checks = validate_popularity_ranking(ranking, expected_total_ratings=expected_total)
    checks["row_count_matches_manifest"] = len(ranking) == expected_rows
    _raise_if_failed(checks, csv_path.name)
    return ranking.astype({col: "int64" for col in RANKING_COLUMNS if col != "average_rating"}), manifest


# ---------------------------------------------------------------------------
# 6. Reusable interface for evaluation and the future recommendation service
# ---------------------------------------------------------------------------


def top_n_popular_movies(
    ranking: pd.DataFrame, n: int, exclude_movie_ids: Iterable[int] | None = None
) -> list[tuple[int, float]]:
    """Return the ``n`` most popular movies as ``(movieId, score)`` pairs, best first.

    ``exclude_movie_ids`` removes movies before the top ``n`` is taken (for example the
    movies a user has already rated), so the result still has ``n`` movies when enough
    remain. IDs that are not in the ranking are ignored. The output format is the one
    expected by the backend helper ``movie_service.build_recommended_movies``.
    """
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 1:
        raise ValueError(f"n must be a positive integer, got {n!r}")
    candidates = ranking
    if exclude_movie_ids is not None:
        excluded = {int(movie_id) for movie_id in exclude_movie_ids}
        if excluded:
            candidates = ranking[~ranking["movieId"].isin(excluded)]
    top = candidates.head(int(n))
    return [
        (int(movie_id), float(score)) for movie_id, score in zip(top["movieId"], top["popularity_score"], strict=True)
    ]


# ---------------------------------------------------------------------------
# 7. Pipeline
# ---------------------------------------------------------------------------


def _read_dataset_manifest(processed_dir: Path) -> dict:
    path = _require_file(Path(processed_dir) / DATA_FILES["manifest"])
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        _ = manifest["outputs"]["train"]["sha256"], manifest["outputs"]["catalogue"]["sha256"]
        _ = manifest["counts"]["train_ratings"], manifest["counts"]["catalogue_movies"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise DataValidationError(f"{path.name} is malformed: {error!r}") from error
    return manifest


def _verify_input_hash(path: Path, expected: str) -> str:
    """The input must be exactly the file validated and recorded by the data pipeline."""
    actual = sha256_of(path)
    if actual != expected:
        raise DataValidationError(
            f"{path.name} does not match the SHA-256 recorded in {DATA_FILES['manifest']}; "
            "it was modified after data preparation. Re-run src.prepare_data."
        )
    return actual


def run_popularity_baseline(
    processed_dir: Path = DEFAULT_PROCESSED_DIR, output_dir: Path = DEFAULT_OUTPUT_DIR, overwrite: bool = False
) -> dict:
    """Compute, validate and write the baseline. Returns the written manifest.

    Note that this function has no parameter for the test file: ``ratings_test.csv`` is
    never opened.
    """
    started = time.perf_counter()
    processed_dir = Path(processed_dir)
    dataset_manifest = _read_dataset_manifest(processed_dir)
    train_path = _require_file(processed_dir / DATA_FILES["train"])
    catalogue_path = _require_file(processed_dir / DATA_FILES["catalogue"])

    _refuse_to_overwrite(output_dir, overwrite)  # checked before the expensive work as well

    logger.info("Verifying input hashes against %s", DATA_FILES["manifest"])
    train_hash = _verify_input_hash(train_path, dataset_manifest["outputs"]["train"]["sha256"])
    catalogue_hash = _verify_input_hash(catalogue_path, dataset_manifest["outputs"]["catalogue"]["sha256"])

    logger.info("Loading %s", train_path.name)
    train = load_training_ratings(train_path)
    catalogue_ids = load_catalogue_movie_ids(catalogue_path)
    if len(train) != dataset_manifest["counts"]["train_ratings"]:
        raise DataValidationError("number of training ratings differs from the dataset manifest")
    if len(catalogue_ids) != dataset_manifest["counts"]["catalogue_movies"]:
        raise DataValidationError("number of catalogue movies differs from the dataset manifest")

    logger.info("Computing popularity from %d training ratings", len(train))
    ranking = build_popularity_ranking(train, catalogue_ids)
    validation = validate_popularity_ranking(ranking, catalogue_ids, expected_total_ratings=len(train))
    n_users = int(train["userId"].nunique())
    del train

    manifest = {
        "baseline": {
            "name": "MovieLens training-set popularity baseline",
            "version": BASELINE_VERSION,
            "script": "ml/src/popularity_baseline.py",
            "algorithm": ALGORITHM,
            "popularity_score": "number of ratings of the movie in ratings_train.csv (popularity_score = rating_count)",
            "ranking_criteria": ["rating_count descending", "movieId ascending (tie-break)"],
            "average_rating": "mean training rating of the movie; complementary information, not used for ranking",
            "personalised": False,
            "parameters": None,  # the method has no tunable parameter
            "random_seed": None,  # fully deterministic
        },
        "source": {
            "dataset": dataset_manifest.get("dataset", {}).get("name"),
            "dataset_version": dataset_manifest.get("dataset", {}).get("version"),
            "data_pipeline_version": dataset_manifest.get("pipeline", {}).get("version"),
            "dataset_manifest": DATA_FILES["manifest"],
            "training_file": DATA_FILES["train"],
            "training_file_sha256": train_hash,
            "catalogue_file": DATA_FILES["catalogue"],
            "catalogue_file_sha256": catalogue_hash,
            "test_file_used": False,
            "identifier": "MovieLens movieId (item_index is not used)",
        },
        "counts": {
            "movies": len(ranking),
            "training_ratings": int(ranking["rating_count"].sum()),
            "training_users": n_users,
        },
        "distribution": describe_popularity_distribution(ranking),
        "validation": validation,
        # The only non-deterministic field: everything else depends only on the input files.
        "run": {"generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds")},
    }
    manifest = write_popularity_baseline(ranking, manifest, output_dir, overwrite)
    logger.info(
        "Finished in %.1f s; wrote %s", time.perf_counter() - started, Path(output_dir) / OUTPUT_FILES["ranking"]
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute the AuraCinema popularity baseline (training data only).")
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=DEFAULT_PROCESSED_DIR,
        help="folder with ratings_train.csv, movies_catalogue.csv and dataset_manifest.json",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="folder for the baseline files")
    parser.add_argument("--overwrite", action="store_true", help="replace outputs from a previous run")
    parser.add_argument("--show-top", type=int, default=10, help="number of top movies to print (0 = none)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    try:
        manifest = run_popularity_baseline(args.processed_dir, args.output_dir, overwrite=args.overwrite)
    except (FileNotFoundError, FileExistsError, DataValidationError) as error:
        logger.error("%s", error)
        raise SystemExit(1) from error
    logger.info(
        "Ranked %d movies from %d training ratings",
        manifest["counts"]["movies"],
        manifest["counts"]["training_ratings"],
    )
    if args.show_top > 0:
        ranking, _ = load_popularity_baseline(args.output_dir)
        for rank, (movie_id, score) in enumerate(top_n_popular_movies(ranking, args.show_top), start=1):
            logger.info("%3d. movieId=%d  training ratings=%d", rank, movie_id, int(score))


if __name__ == "__main__":
    main()
