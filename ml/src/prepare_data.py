"""Prepare the MovieLens 32M data for the AuraCinema recommendation engine.

This script turns the raw MovieLens files into a small, documented set of outputs:

* ``ratings_train.csv``  - ratings the model is allowed to learn from.
* ``ratings_test.csv``   - later ratings held out for evaluation only.
* ``movies_catalogue.csv`` - selected movies with MovieLens and TMDB identifiers.
* ``movie_index_map.csv`` - stable mapping between ``movieId`` and a matrix index.
* ``dataset_manifest.json`` - what was produced, from what, and with which settings.
* ``data_quality_report.json`` - the statistics and validation results of the run.

It does NOT train a model. It only prepares reliable input for that later step.

Usage (from the ``ml`` folder)::

    python -m src.prepare_data --overwrite

Run ``python -m src.prepare_data --help`` to see all options.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PIPELINE_VERSION = "1.0.0"

# Paths are resolved from this file, so the script works from any working directory.
ML_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ML_ROOT / "data" / "ml-32m"
DEFAULT_OUTPUT_DIR = ML_ROOT / "data" / "processed"
DEFAULT_REPORT_PATH = ML_ROOT / "docs" / "data_quality_report.json"

SOURCE_URL = "https://grouplens.org/datasets/movielens/32m/"

# Only the files needed by the methodology are loaded. tags.csv is not used:
# item-based collaborative filtering only needs ratings, and genres come from movies.csv.
REQUIRED_COLUMNS = {
    "ratings.csv": ["userId", "movieId", "rating", "timestamp"],
    "movies.csv": ["movieId", "title", "genres"],
    "links.csv": ["movieId", "imdbId", "tmdbId"],
}
# Columns that must be numeric. tmdbId may contain empty values, so pandas reads it as float.
NUMERIC_COLUMNS = {
    "ratings.csv": ["userId", "movieId", "rating", "timestamp"],
    "movies.csv": ["movieId"],
    "links.csv": ["movieId", "imdbId", "tmdbId"],
}

# MovieLens uses a 5-star scale with half-star steps (0.5 to 5.0).
VALID_RATINGS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
NO_GENRES_LABEL = "(no genres listed)"

OUTPUT_FILES = {
    "train": "ratings_train.csv",
    "test": "ratings_test.csv",
    "catalogue": "movies_catalogue.csv",
    "index_map": "movie_index_map.csv",
    "manifest": "dataset_manifest.json",
}

logger = logging.getLogger("prepare_data")


class DataValidationError(Exception):
    """Raised when the input data or the prepared data break a required rule."""


@dataclass
class PreparationConfig:
    """Selection and split parameters. The defaults are the values used for AuraCinema."""

    # Keep the N movies with the most ratings (ties broken by the smaller movieId).
    top_n_movies: int = 5000
    # Guarantee each genre at least this many of its most-rated movies ...
    genre_floor_movies: int = 100
    # ... but only movies with at least this many ratings, so the similarities stay reliable.
    genre_floor_min_ratings: int = 100
    # A user needs at least this many ratings (inside the selected movies) to be kept.
    min_user_ratings: int = 20
    # Share of each user's latest ratings reserved for the test set.
    test_fraction: float = 0.2


# ---------------------------------------------------------------------------
# 1. Loading and validating the source files
# ---------------------------------------------------------------------------


def load_source_data(input_dir: Path) -> dict[str, pd.DataFrame]:
    """Read ratings.csv, movies.csv and links.csv from ``input_dir``.

    Raises FileNotFoundError with a clear message if a required file is missing.
    """
    input_dir = Path(input_dir)
    missing = [name for name in REQUIRED_COLUMNS if not (input_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Required MovieLens file(s) not found in '{input_dir}': {', '.join(missing)}. "
            f"Download MovieLens 32M from {SOURCE_URL} and extract it there, or pass --input-dir."
        )

    data = {}
    for name in REQUIRED_COLUMNS:
        logger.info("Loading %s", name)
        data[name] = pd.read_csv(input_dir / name)
    return data


def verify_checksums(input_dir: Path) -> dict:
    """Compare the MD5 hash of each used file with the checksums.txt shipped by GroupLens.

    This confirms that the local files are the official, unmodified ML-32M release.
    If checksums.txt is absent (e.g. synthetic test data) the check is reported as skipped.
    """
    checksum_file = Path(input_dir) / "checksums.txt"
    if not checksum_file.is_file():
        return {"status": "skipped", "reason": "checksums.txt not found"}

    expected = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            expected[parts[1]] = parts[0].lower()

    results = {}
    for name in REQUIRED_COLUMNS:
        md5 = hashlib.md5()
        with open(Path(input_dir) / name, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                md5.update(block)
        results[name] = md5.hexdigest() == expected.get(name)

    if not all(results.values()):
        failed = [name for name, ok in results.items() if not ok]
        raise DataValidationError(
            f"MD5 checksum mismatch for {failed}. The files are not the expected MovieLens 32M release."
        )
    return {"status": "passed", "files": results}


def validate_source_data(data: dict[str, pd.DataFrame]) -> None:
    """Check the structure of the source tables: required columns and numeric types.

    Structural problems make the whole file unusable, so they stop the pipeline.
    Problems in individual records (e.g. one invalid rating) are handled later by
    ``clean_ratings``, which excludes and counts them instead of failing.
    """
    for name, columns in REQUIRED_COLUMNS.items():
        frame = data[name]
        missing = [col for col in columns if col not in frame.columns]
        if missing:
            raise DataValidationError(f"{name} is missing required column(s): {', '.join(missing)}")
        for col in NUMERIC_COLUMNS[name]:
            if not pd.api.types.is_numeric_dtype(frame[col]) or pd.api.types.is_bool_dtype(frame[col]):
                raise DataValidationError(
                    f"{name}: column '{col}' must be numeric but was read as {frame[col].dtype}"
                )

    movies = data["movies.csv"]
    if movies["movieId"].isna().any() or movies["movieId"].duplicated().any():
        raise DataValidationError("movies.csv: movieId must be present and unique for every movie")


def describe_source_structure(data: dict[str, pd.DataFrame]) -> dict:
    """Rows, columns and data types of each source file (before any cleaning)."""
    return {
        name: {
            "rows": len(frame),
            "columns": len(frame.columns),
            "dtypes": {col: str(dtype) for col, dtype in frame.dtypes.items()},
        }
        for name, frame in data.items()
    }


def clean_ratings(ratings: pd.DataFrame, known_movie_ids: pd.Series) -> tuple[pd.DataFrame, dict]:
    """Exclude invalid rating records and return the clean table plus the exclusion counts.

    Rules (each record is counted under the first rule it breaks):
    * missing value in any column            -> excluded (cannot be used or repaired)
    * userId / movieId not a positive integer -> excluded
    * rating not in 0.5, 1.0, ..., 5.0        -> excluded (not on the MovieLens scale)
    * timestamp not a positive integer or in the future -> excluded
    * movieId not present in movies.csv       -> excluded (no metadata to show the user)
    * duplicate (userId, movieId) pair        -> keep the most recent rating only, which
      matches how the AuraCinema backend stores one current rating per user and movie.
    """
    exclusions: dict[str, int] = {}
    df = ratings[REQUIRED_COLUMNS["ratings.csv"]]
    now = time.time()

    def exclude(mask: pd.Series, reason: str) -> None:
        nonlocal df
        exclusions[reason] = int(mask.sum())
        if mask.any():
            df = df[~mask]

    exclude(df.isna().any(axis=1), "missing_values")
    exclude(
        (df["userId"] <= 0) | (df["userId"] % 1 != 0) | (df["movieId"] <= 0) | (df["movieId"] % 1 != 0),
        "invalid_identifier",
    )
    exclude(~df["rating"].isin(VALID_RATINGS), "invalid_rating")
    exclude((df["timestamp"] <= 0) | (df["timestamp"] % 1 != 0) | (df["timestamp"] > now), "invalid_timestamp")
    exclude(~df["movieId"].isin(known_movie_ids), "unknown_movie")

    # Sort so that, for a duplicated pair, the latest rating is the last row and is kept.
    # A stable sort keeps file order when two duplicates share the same timestamp.
    df = df.sort_values(["userId", "movieId", "timestamp"], kind="mergesort")
    exclude(df.duplicated(["userId", "movieId"], keep="last"), "duplicate_pair_older_rating")

    df = df.astype({"userId": "int32", "movieId": "int32", "rating": "float64", "timestamp": "int64"})
    return df.reset_index(drop=True), exclusions


# ---------------------------------------------------------------------------
# 2. Inspection helpers (statistics for the data-quality report)
# ---------------------------------------------------------------------------


def to_utc_iso(timestamp: int) -> str:
    """Convert Unix seconds (UTC, as used by MovieLens) to an ISO 8601 UTC string."""
    return pd.to_datetime(int(timestamp), unit="s", utc=True).isoformat()


def split_genres(movies: pd.DataFrame) -> pd.DataFrame:
    """One row per (movieId, genre). A movie with three genres produces three rows."""
    exploded = movies[["movieId", "genres"]].assign(genre=movies["genres"].str.split("|"))
    return exploded.explode("genre")[["movieId", "genre"]]


def matrix_sparsity(ratings: pd.DataFrame) -> dict:
    """Size and sparsity of the user-item matrix, computed from counts only.

    A dense matrix is never built: for the full dataset it would need about
    200,948 x 84,432 = 17 billion cells.
    """
    n_users = ratings["userId"].nunique()
    n_movies = ratings["movieId"].nunique()
    n_ratings = len(ratings)
    cells = n_users * n_movies
    density = n_ratings / cells if cells else 0.0
    return {
        "users": n_users,
        "movies": n_movies,
        "ratings": n_ratings,
        "matrix_cells": cells,
        "density": round(density, 6),
        "sparsity": round(1 - density, 6),
    }


def user_span_days(ratings: pd.DataFrame) -> pd.Series:
    """Days between each user's first and last rating (0 if all ratings share one second)."""
    bounds = ratings.groupby("userId")["timestamp"].agg(["min", "max"])
    return (bounds["max"] - bounds["min"]) / 86400


def temporal_summary(ratings: pd.DataFrame) -> dict:
    """Timestamp range, ratings per year and how long each user's history lasts."""
    span_days = user_span_days(ratings)
    active_days = (ratings["timestamp"] // 86400).groupby(ratings["userId"]).nunique()
    years = pd.to_datetime(ratings["timestamp"], unit="s", utc=True).dt.year
    return {
        "earliest_rating_utc": to_utc_iso(ratings["timestamp"].min()),
        "latest_rating_utc": to_utc_iso(ratings["timestamp"].max()),
        "ratings_per_year": {int(y): int(c) for y, c in years.value_counts().sort_index().items()},
        "user_history_span_days_percentiles": {
            f"p{int(q * 100)}": round(float(v), 1) for q, v in span_days.quantile([0.25, 0.5, 0.75, 0.9]).items()
        },
        "users_with_span_over_1_day": int((span_days > 1).sum()),
        "users_with_span_over_365_days": int((span_days > 365).sum()),
        "share_users_span_over_365_days": round(float((span_days > 365).mean()), 4),
        "user_distinct_active_days_median": float(active_days.median()),
    }


def inspect_dataset(ratings: pd.DataFrame, movies: pd.DataFrame, links: pd.DataFrame) -> dict:
    """Statistics of the full (cleaned) dataset: users, movies, genres, activity, sparsity, time."""
    user_counts = ratings.groupby("userId").size()
    movie_counts = ratings.groupby("movieId").size().sort_values(ascending=False)
    genres = split_genres(movies)
    rated_genres = genres[genres["movieId"].isin(movie_counts.index)]

    top_movies = (
        movie_counts.head(10).rename("rating_count").reset_index()
        .merge(movies[["movieId", "title"]], on="movieId", how="left")
    )
    # Long tail: what share of all ratings goes to the most-rated 1% and 10% of movies.
    cumulative = movie_counts.cumsum() / len(ratings)
    n_rated = len(movie_counts)

    return {
        "ratings": len(ratings),
        "distinct_users": int(ratings["userId"].nunique()),
        "distinct_rated_movies": n_rated,
        "movies_in_catalogue_file": len(movies),
        "catalogue_movies_without_ratings": int((~movies["movieId"].isin(movie_counts.index)).sum()),
        "distinct_rating_timestamps": int(ratings["timestamp"].nunique()),
        "distinct_genres_including_no_genre_label": int(genres["genre"].nunique()),
        "movies_with_no_genres_listed": int((movies["genres"] == NO_GENRES_LABEL).sum()),
        "rating_value_counts": {str(k): int(v) for k, v in ratings["rating"].value_counts().sort_index().items()},
        "mean_rating": round(float(ratings["rating"].mean()), 4),
        "tmdb": {
            "links_rows": len(links),
            "movies_without_links_row": int((~movies["movieId"].isin(links["movieId"])).sum()),
            "missing_tmdb_id_all_movies": int(links["tmdbId"].isna().sum()),
            "missing_tmdb_id_rated_movies": int(
                links.loc[links["movieId"].isin(movie_counts.index), "tmdbId"].isna().sum()
            ),
            "tmdb_ids_shared_by_several_movies": int(links["tmdbId"].dropna().duplicated().sum()),
        },
        "user_activity": {
            "mean": round(float(user_counts.mean()), 2),
            "min": int(user_counts.min()),
            "max": int(user_counts.max()),
            "percentiles": {
                f"p{int(q * 100)}": float(v)
                for q, v in user_counts.quantile([0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]).items()
            },
            "users_below_20_ratings": int((user_counts < 20).sum()),
            "users_below_50_ratings": int((user_counts < 50).sum()),
        },
        "movie_activity": {
            "mean": round(float(movie_counts.mean()), 2),
            "median": float(movie_counts.median()),
            "max": int(movie_counts.max()),
            "movies_with_fewer_than": {
                str(t): int((movie_counts < t).sum()) for t in [5, 10, 20, 50, 100, 500, 1000]
            },
            "share_of_ratings_top_1pct_movies": round(float(cumulative.iloc[max(1, n_rated // 100) - 1]), 4),
            "share_of_ratings_top_10pct_movies": round(float(cumulative.iloc[max(1, n_rated // 10) - 1]), 4),
            "most_rated_movies": top_movies.to_dict(orient="records"),
        },
        "genres": {
            "movies_per_genre": rated_genres.groupby("genre").size().sort_values(ascending=False).to_dict(),
        },
        "sparsity": matrix_sparsity(ratings),
        "temporal": temporal_summary(ratings),
    }


# ---------------------------------------------------------------------------
# 3. Dataset selection
# ---------------------------------------------------------------------------


def select_dataset_subset(
    ratings: pd.DataFrame, movies: pd.DataFrame, config: PreparationConfig
) -> tuple[pd.DataFrame, dict]:
    """Apply the documented selection rule, in this fixed order:

    1. Movies: the ``top_n_movies`` most-rated movies (ties -> smaller movieId first),
       plus a genre floor: for every genre, its ``genre_floor_movies`` most-rated movies
       that have at least ``genre_floor_min_ratings`` ratings. "(no genres listed)" is not
       a genre and gets no floor.
    2. Ratings: keep only ratings of the selected movies.
    3. Users: keep users with at least ``min_user_ratings`` ratings among those movies.

    The rule is applied once (not repeated until stable) so it stays easy to explain.
    Returns the selected ratings and a log of how many records each stage kept.
    """
    movie_counts = ratings.groupby("movieId").size().rename("rating_count").reset_index()
    # Sorting by count (descending) then movieId (ascending) gives a unique, reproducible order.
    ranked = movie_counts.sort_values(["rating_count", "movieId"], ascending=[False, True])
    top_ids = set(ranked["movieId"].head(config.top_n_movies))

    genre_rows = ranked.merge(split_genres(movies), on="movieId", how="inner")
    genre_rows = genre_rows[
        (genre_rows["genre"] != NO_GENRES_LABEL) & (genre_rows["rating_count"] >= config.genre_floor_min_ratings)
    ]
    genre_rows = genre_rows.sort_values(["genre", "rating_count", "movieId"], ascending=[True, False, True])
    floor_ids = set(genre_rows.groupby("genre").head(config.genre_floor_movies)["movieId"])
    selected_ids = top_ids | floor_ids

    stage_movies = ratings[ratings["movieId"].isin(selected_ids)]
    user_counts = stage_movies.groupby("userId")["movieId"].transform("size")
    stage_users = stage_movies[user_counts >= config.min_user_ratings].reset_index(drop=True)

    def stage(name: str, frame: pd.DataFrame) -> dict:
        return {
            "stage": name,
            "users": int(frame["userId"].nunique()),
            "movies": int(frame["movieId"].nunique()),
            "ratings": len(frame),
        }

    info = {
        "movies_from_top_n": len(top_ids),
        "movies_added_by_genre_floor": len(floor_ids - top_ids),
        "selected_movies": len(selected_ids),
        "min_rating_count_in_top_n": int(ranked["rating_count"].head(config.top_n_movies).min()),
        "stages": [
            stage("0_clean_full_dataset", ratings),
            stage("1_selected_movies", stage_movies),
            stage("2_users_with_min_ratings", stage_users),
        ],
    }
    return stage_users, info


def describe_subset(subset: pd.DataFrame, movies: pd.DataFrame, total_ratings: int) -> dict:
    """Compact statistics used to compare candidate subsets."""
    genres = split_genres(movies[movies["movieId"].isin(subset["movieId"].unique())])
    genre_movies = genres[genres["genre"] != NO_GENRES_LABEL].groupby("genre").size()
    span_days = user_span_days(subset)
    return {
        **matrix_sparsity(subset),
        "share_of_all_ratings": round(len(subset) / total_ratings, 4),
        "genres_represented": int(len(genre_movies)),
        "smallest_genre": {"genre": str(genre_movies.idxmin()), "movies": int(genre_movies.min())},
        "users_with_span_over_365_days": int((span_days > 365).sum()),
    }


def compare_candidate_subsets(ratings: pd.DataFrame, movies: pd.DataFrame, config: PreparationConfig) -> list[dict]:
    """Evaluate a few candidate rules so the final choice is justified by observed numbers."""
    candidates = [
        ("top_2000_no_floor", PreparationConfig(2000, 0, config.genre_floor_min_ratings, config.min_user_ratings)),
        ("top_5000_no_floor", PreparationConfig(5000, 0, config.genre_floor_min_ratings, config.min_user_ratings)),
        ("top_10000_no_floor", PreparationConfig(10000, 0, config.genre_floor_min_ratings, config.min_user_ratings)),
        ("selected_rule", config),
    ]
    results = []
    for name, candidate in candidates:
        logger.info("Evaluating candidate subset: %s", name)
        subset, _ = select_dataset_subset(ratings, movies, candidate)
        results.append({"candidate": name, "parameters": asdict(candidate),
                        **describe_subset(subset, movies, len(ratings))})
    return results


# ---------------------------------------------------------------------------
# 4. Training / test split
# ---------------------------------------------------------------------------


def split_ratings_by_user(
    ratings: pd.DataFrame, test_fraction: float, min_user_ratings: int
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Chronological per-user split.

    For every user the ratings are ordered by (timestamp, movieId). The movieId is a
    tie-breaker: when two ratings have the same second, the smaller movieId counts as
    earlier. This gives one fixed order, so the split is always the same.

    The latest ``floor(n * test_fraction)`` ratings (at least 1) go to the test set and
    the earlier ones to the training set. Users with fewer than ``min_user_ratings``
    ratings are excluded from both sets and counted in the returned statistics.
    """
    ordered = ratings.sort_values(["userId", "timestamp", "movieId"]).reset_index(drop=True)
    counts = ordered.groupby("userId")["movieId"].transform("size")

    eligible = counts >= min_user_ratings
    excluded_users = int(ordered.loc[~eligible, "userId"].nunique())
    ordered, counts = ordered[eligible], counts[eligible]

    # Position of each rating in the user's history: 0 = oldest.
    # We need to split each user's rating history individually, 
    # avoiding to depend on a rating's global position inside the DataFrame.
    position = ordered.groupby("userId").cumcount()
    # The small epsilon avoids floating-point surprises such as 0.29 * 100 = 28.999999...
    n_test = np.maximum(1, np.floor(counts * test_fraction + 1e-9)).astype("int64")
    is_test = position >= counts - n_test

    train = ordered[~is_test].reset_index(drop=True)
    test = ordered[is_test].reset_index(drop=True)

    # Users whose last training rating and first test rating share the same second:
    # for them the movieId tie-breaker decided the boundary.
    last_train = train.groupby("userId")["timestamp"].max()
    first_test = test.groupby("userId")["timestamp"].min()
    boundary_ties = int((last_train == first_test.reindex(last_train.index)).sum())

    stats = {
        "eligible_users": int(ordered["userId"].nunique()),
        "excluded_users_insufficient_history": excluded_users,
        "train_ratings": len(train),
        "test_ratings_before_eligibility": len(test),
        "users_with_boundary_timestamp_tie": boundary_ties,
    }
    return train, test, stats


def apply_evaluation_eligibility(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Remove test ratings of movies that never appear in the training set.

    Item-based collaborative filtering can only score a movie through its similarity to
    other movies, which is learnt from training ratings. A movie without any training
    rating cannot be recommended, so keeping it would measure a case the model cannot
    handle by design. These rows are dropped (not moved to training, which would break
    the chronological order) and reported.
    """
    known = test["movieId"].isin(train["movieId"].unique())
    eligible_test = test[known].reset_index(drop=True)
    stats = {
        "test_ratings_removed_movie_not_in_train": int((~known).sum()),
        "movies_removed_from_test": int(test.loc[~known, "movieId"].nunique()),
        "users_left_without_test_ratings": int(test["userId"].nunique() - eligible_test["userId"].nunique()),
        "test_ratings": len(eligible_test),
        "test_users": int(eligible_test["userId"].nunique()),
    }
    return eligible_test, stats


def compute_training_movie_stats(train: pd.DataFrame) -> pd.DataFrame:
    """Per-movie rating count and mean computed from TRAINING ratings only.

    Anything rating-derived (popularity, averages, similarities) must come from the
    training set; this function deliberately takes no test data.
    """
    stats = train.groupby("movieId")["rating"].agg(train_rating_count="size", train_mean_rating="mean")
    return stats.reset_index().sort_values(["train_rating_count", "movieId"], ascending=[False, True])


# ---------------------------------------------------------------------------
# 5. Movie catalogue and index mapping
# ---------------------------------------------------------------------------


def prepare_movie_catalogue(movies: pd.DataFrame, links: pd.DataFrame, movie_ids) -> pd.DataFrame:
    """Selected movies with their MovieLens id, title, genres, IMDb id and TMDB id.

    The left join keeps every selected movie even when links.csv has no TMDB id for it.
    Missing TMDB ids stay empty (never guessed); the backend can still show the movie
    using its MovieLens title and genres. Non-positive TMDB ids are treated as missing.
    """
    catalogue = movies.loc[movies["movieId"].isin(movie_ids), ["movieId", "title", "genres"]]
    link_cols = links[["movieId", "imdbId", "tmdbId"]].drop_duplicates("movieId")
    catalogue = catalogue.merge(link_cols, on="movieId", how="left")
    catalogue["tmdbId"] = catalogue["tmdbId"].where(catalogue["tmdbId"] > 0)
    # Nullable integers: written as e.g. 862 instead of 862.0, and empty when missing.
    catalogue = catalogue.astype({"movieId": "int32", "imdbId": "Int64", "tmdbId": "Int64"})
    return catalogue.sort_values("movieId").reset_index(drop=True)


def build_movie_index_map(train: pd.DataFrame) -> pd.DataFrame:
    """Map each training movieId to a 0-based matrix column index (sorted by movieId).

    The model will use ``item_index`` internally; the original ``movieId`` is always
    recoverable through this table.
    """
    movie_ids = np.sort(train["movieId"].unique())
    return pd.DataFrame({"item_index": np.arange(len(movie_ids), dtype="int32"), "movieId": movie_ids})


# ---------------------------------------------------------------------------
# 6. Validation of the prepared data
# ---------------------------------------------------------------------------


def validate_prepared_data(
    train: pd.DataFrame,
    test: pd.DataFrame,
    catalogue: pd.DataFrame,
    index_map: pd.DataFrame,
    config: PreparationConfig,
) -> dict[str, bool]:
    """Run the leakage and consistency checks. Returns check name -> passed."""
    pair_cols = ["userId", "movieId"]
    overlap = train[pair_cols].merge(test[pair_cols], on=pair_cols, how="inner")

    # Chronological order with tie-breaking: the user's last training rating must come
    # strictly before the first test rating in (timestamp, movieId) order.
    last_train = train.sort_values(["userId", "timestamp", "movieId"]).groupby("userId").tail(1)
    first_test = test.sort_values(["userId", "timestamp", "movieId"]).groupby("userId").head(1)
    boundary = first_test.merge(last_train, on="userId", how="left", suffixes=("_test", "_train"))
    chronological = (boundary["timestamp_train"] < boundary["timestamp_test"]) | (
        (boundary["timestamp_train"] == boundary["timestamp_test"])
        & (boundary["movieId_train"] < boundary["movieId_test"])
    )

    # Smallest training history a kept user can have, e.g. 20 - floor(20 * 0.2) = 16.
    min_train = config.min_user_ratings - int(np.floor(config.min_user_ratings * config.test_fraction + 1e-9))
    train_per_test_user = train.groupby("userId").size().reindex(test["userId"].unique(), fill_value=0)

    expected_index = np.arange(len(index_map))
    return {
        "train_test_pairs_disjoint": overlap.empty,
        "no_duplicate_pairs_in_train": not train.duplicated(pair_cols).any(),
        "no_duplicate_pairs_in_test": not test.duplicated(pair_cols).any(),
        "train_precedes_test_for_every_user": bool(chronological.all()),
        "every_test_user_has_min_train_history": bool((train_per_test_user >= min_train).all()),
        "ratings_valid_in_train": bool(train["rating"].isin(VALID_RATINGS).all()),
        "ratings_valid_in_test": bool(test["rating"].isin(VALID_RATINGS).all()),
        "train_movies_in_catalogue": bool(train["movieId"].isin(catalogue["movieId"]).all()),
        "test_movies_in_catalogue": bool(test["movieId"].isin(catalogue["movieId"]).all()),
        "test_movies_in_index_map": bool(test["movieId"].isin(index_map["movieId"]).all()),
        "catalogue_movie_ids_unique": not catalogue["movieId"].duplicated().any(),
        "index_map_contiguous_and_unique": bool(
            (index_map["item_index"].to_numpy() == expected_index).all() and index_map["movieId"].is_unique
        ),
    }


# ---------------------------------------------------------------------------
# 7. Writing the outputs
# ---------------------------------------------------------------------------


def _json_default(value):
    """Let json.dump handle NumPy and pandas scalar types."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NA:
        return None
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_dataset_outputs(
    frames: dict[str, pd.DataFrame],
    manifest: dict,
    report: dict,
    output_dir: Path,
    report_path: Path,
    overwrite: bool = False,
) -> dict:
    """Write the CSV files, the manifest and the data-quality report.

    Only the known output file names are written. Existing outputs are replaced only
    when ``overwrite`` is True, so a previous run is never replaced by accident.
    """
    output_dir, report_path = Path(output_dir), Path(report_path)
    targets = [output_dir / OUTPUT_FILES[key] for key in OUTPUT_FILES] + [report_path]
    existing = [str(p) for p in targets if p.exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Output file(s) already exist: {existing}. Use --overwrite to replace them.")

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    outputs = {}
    for key, frame in frames.items():
        path = output_dir / OUTPUT_FILES[key]
        logger.info("Writing %s (%d rows)", path.name, len(frame))
        frame.to_csv(path, index=False, lineterminator="\n")
        outputs[key] = {
            "file": path.name,
            "rows": len(frame),
            "columns": list(frame.columns),
            "sha256": sha256_of(path),
        }

    manifest = {**manifest, "outputs": outputs, "data_quality_report": report_path.name}
    with open(output_dir / OUTPUT_FILES["manifest"], "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, default=_json_default)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=_json_default)
    return manifest


# ---------------------------------------------------------------------------
# 8. Pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
    config: PreparationConfig | None = None,
    overwrite: bool = False,
    compare_candidates: bool = True,
) -> dict:
    """Run every step in order and return the manifest that was written."""
    config = config or PreparationConfig()
    started = time.time()

    data = load_source_data(input_dir)
    checksums = verify_checksums(input_dir)
    validate_source_data(data)
    source_structure = describe_source_structure(data)

    movies, links = data["movies.csv"], data["links.csv"]
    ratings, exclusions = clean_ratings(data["ratings.csv"], movies["movieId"])
    del data  # free the raw ratings table (about 1 GB for the full dataset)
    logger.info("Clean ratings: %d (excluded: %s)", len(ratings), exclusions)

    logger.info("Inspecting the full dataset")
    inspection = inspect_dataset(ratings, movies, links)
    candidates = compare_candidate_subsets(ratings, movies, config) if compare_candidates else []

    logger.info("Selecting the subset")
    subset, selection = select_dataset_subset(ratings, movies, config)
    total_clean_ratings = len(ratings)
    del ratings

    logger.info("Splitting into training and test sets")
    train, test_raw, split_stats = split_ratings_by_user(subset, config.test_fraction, config.min_user_ratings)
    test, eligibility = apply_evaluation_eligibility(train, test_raw)

    catalogue = prepare_movie_catalogue(movies, links, subset["movieId"].unique())
    index_map = build_movie_index_map(train)
    del subset, test_raw

    validation = validate_prepared_data(train, test, catalogue, index_map, config)
    if not all(validation.values()):
        failed = [name for name, ok in validation.items() if not ok]
        raise DataValidationError(f"Prepared data failed validation checks: {failed}")
    logger.info("All %d validation checks passed", len(validation))

    train_movie_stats = compute_training_movie_stats(train)
    train_span = user_span_days(train)
    all_prepared = pd.concat([train, test])

    counts = {
        "users": int(train["userId"].nunique()),
        "test_users": eligibility["test_users"],
        "catalogue_movies": len(catalogue),
        "train_movies": len(index_map),
        "train_ratings": len(train),
        "test_ratings": len(test),
        "catalogue_movies_missing_tmdb_id": int(catalogue["tmdbId"].isna().sum()),
    }
    timestamp_range = {
        "earliest_utc": to_utc_iso(all_prepared["timestamp"].min()),
        "latest_utc": to_utc_iso(all_prepared["timestamp"].max()),
    }

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pipeline_version": PIPELINE_VERSION,
        "parameters": asdict(config),
        "source_checksums": checksums,
        "source_structure": source_structure,
        "cleaning_exclusions": exclusions,
        "full_dataset": inspection,
        "candidate_subsets": candidates,
        "selection": selection,
        "split": {**split_stats, **eligibility},
        "prepared_dataset": {
            **counts,
            "timestamp_range": timestamp_range,
            "sparsity_train": matrix_sparsity(train),
            "train_ratings_per_user_median": float(train.groupby("userId").size().median()),
            "test_ratings_per_user_median": float(test.groupby("userId").size().median()),
            "train_ratings_per_movie_min": int(train_movie_stats["train_rating_count"].min()),
            "train_ratings_per_movie_median": float(train_movie_stats["train_rating_count"].median()),
            "train_users_with_span_over_365_days": int((train_span > 365).sum()),
            "catalogue_duplicate_tmdb_ids": int(catalogue["tmdbId"].dropna().duplicated().sum()),
            "catalogue_movies_with_no_genres_listed": int((catalogue["genres"] == NO_GENRES_LABEL).sum()),
            "catalogue_movies_per_genre": split_genres(catalogue).groupby("genre").size().to_dict(),
            "temporal_all_prepared_ratings": temporal_summary(all_prepared),
        },
        "validation": validation,
    }

    manifest = {
        "dataset": {
            "name": "MovieLens 32M",
            "publisher": "GroupLens Research, University of Minnesota",
            "source_url": SOURCE_URL,
            "version": "ml-32m (generated 13 October 2023)",
            "files_used": list(REQUIRED_COLUMNS),
            "checksum_verification": checksums.get("status"),
        },
        "pipeline": {
            "script": "ml/src/prepare_data.py",
            "version": PIPELINE_VERSION,
            "run_at_utc": report["generated_at_utc"],
        },
        "parameters": asdict(config),
        "random_seed": None,  # the pipeline is fully deterministic and uses no randomness
        "timestamp_convention": "Unix epoch seconds (UTC), unchanged from MovieLens",
        "split_method": "chronological per-user split; order (timestamp, movieId); latest "
        f"floor(n * {config.test_fraction}) ratings per user to test",
        "counts": counts,
        "timestamp_range": timestamp_range,
        "validation": validation,
    }

    frames = {"train": train, "test": test, "catalogue": catalogue, "index_map": index_map}
    manifest = write_dataset_outputs(frames, manifest, report, output_dir, report_path, overwrite)
    logger.info("Finished in %.1f s", time.time() - started)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    defaults = PreparationConfig()
    parser = argparse.ArgumentParser(description="Prepare MovieLens 32M data for AuraCinema.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="folder with the MovieLens CSV files")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="folder for the processed files")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH, help="data-quality report (JSON)")
    parser.add_argument("--top-n-movies", type=int, default=defaults.top_n_movies)
    parser.add_argument("--genre-floor-movies", type=int, default=defaults.genre_floor_movies)
    parser.add_argument("--genre-floor-min-ratings", type=int, default=defaults.genre_floor_min_ratings)
    parser.add_argument("--min-user-ratings", type=int, default=defaults.min_user_ratings)
    parser.add_argument("--test-fraction", type=float, default=defaults.test_fraction)
    parser.add_argument("--skip-candidates", action="store_true", help="skip the candidate subset comparison")
    parser.add_argument("--overwrite", action="store_true", help="replace outputs from a previous run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    if not 0 < args.test_fraction < 1:
        raise SystemExit("--test-fraction must be between 0 and 1")
    config = PreparationConfig(
        top_n_movies=args.top_n_movies,
        genre_floor_movies=args.genre_floor_movies,
        genre_floor_min_ratings=args.genre_floor_min_ratings,
        min_user_ratings=args.min_user_ratings,
        test_fraction=args.test_fraction,
    )
    try:
        run_pipeline(args.input_dir, args.output_dir, args.report_path, config,
                     overwrite=args.overwrite, compare_candidates=not args.skip_candidates)
    except (FileNotFoundError, FileExistsError, DataValidationError) as error:
        logger.error("%s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
