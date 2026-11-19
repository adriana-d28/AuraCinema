"""Item-based collaborative filtering (CF) for the AuraCinema recommendation engine.

The model learns which movies are related from the way MovieLens users rated them
(Sarwar et al., 2001). Only user-movie ratings are used: no title, genre or TMDB data.

Method (justified in ml/docs/collaborative_filtering_implementation.md):

1. Sparse user x item rating matrix from TRAINING ratings; columns are the ``item_index``
   of ``movie_index_map.csv``.
2. Mean-centring by user: ``c_ui = r_ui - mean_u`` (``mean_u`` = mean of the user's
   ratings in the data the model is trained on). Unrated cells stay empty (= 0).
3. Adjusted cosine similarity = cosine between the mean-centred item columns:
   ``sim(i, j) = c_i . c_j / (||c_i|| ||c_j||)``. The dot product only involves users who
   rated both movies; the norms use all raters of each movie.
4. For every movie only its ``k`` most similar POSITIVE neighbours are kept (ties broken
   by smaller ``movieId``). Zero and negative similarities are dropped.
5. Score of an unrated candidate ``j`` for user ``u``, using the neighbours of ``j`` the
   user has rated (``N_k(j) & I_u``). The final model uses the similarity-weighted SUM of
   the user's rating deviations (Deshpande and Karypis, 2004)::

       weighted_sum:      score(u, j) = sum(sim(j, i) * c_ui)

   The normalised weighted average of the project brief (Sarwar et al., 2001) is kept as
   a variant; it was rejected on the internal validation split because most of its top
   scores were exactly 5.0 and supported by a single neighbour::

       weighted_average:  score(u, j) = mean_u + sum(sim(j, i) * c_ui) / sum(|sim(j, i)|)

   Candidates with no rated neighbour get no score (no popularity fallback).

``item_index`` never leaves this module: every public function takes and returns the
MovieLens ``movieId``. ``ratings_test.csv`` is never opened here: the training entry point
``run_cf_training`` has no parameter for it and never builds its path.

Outputs (written to ``ml/data/models/`` by default):

* ``cf_item_neighbours.npz`` - sparse item x item matrix: row j holds sim(j, i) for the
  kept neighbours i of movie j (``scipy.sparse.save_npz``);
* ``cf_model_manifest.json`` - method, configuration, source hashes, counts, artefact hash.

Usage (from the ``ml`` folder)::

    python -m src.collaborative_filtering                  # refuses to replace existing outputs
    python -m src.collaborative_filtering --overwrite --neighbours 50
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

# Reused from the earlier phases instead of being duplicated.
from src.popularity_baseline import (
    _check_columns,
    _read_dataset_manifest,
    _require_file,
    _verify_input_hash,
    load_catalogue_movie_ids,
    load_training_ratings,
    validate_training_ratings,
)
from src.prepare_data import OUTPUT_FILES as DATA_FILES
from src.prepare_data import VALID_RATINGS, DataValidationError, _json_default, sha256_of

MODEL_VERSION = "1.0.0"
ALGORITHM = "item_based_cf_adjusted_cosine_top_k_positive"
# Both selected on the internal validation split (see evaluate_recommendations.run_cf_validation).
SCORING_METHODS = ("weighted_sum", "weighted_average")
DEFAULT_SCORING = "weighted_sum"
DEFAULT_NEIGHBOURS = 50
# Items whose similarities are computed together; bounds the dense block to n_items x 512.
BLOCK_SIZE = 512

ML_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = ML_ROOT / "data" / "processed"
DEFAULT_OUTPUT_DIR = ML_ROOT / "data" / "models"
# Written by ``python -m src.evaluate_recommendations validate``; recorded in the model manifest.
DEFAULT_VALIDATION_RESULTS = ML_ROOT / "data" / "evaluation" / "cf_validation_results.json"

OUTPUT_FILES = {
    "neighbours": "cf_item_neighbours.npz",
    "manifest": "cf_model_manifest.json",
}
INDEX_MAP_COLUMNS = ["item_index", "movieId"]

logger = logging.getLogger("collaborative_filtering")


# ---------------------------------------------------------------------------
# 1. Inputs: index map and sparse rating matrix
# ---------------------------------------------------------------------------


def load_movie_index_map(path: Path) -> pd.DataFrame:
    """Read ``movie_index_map.csv`` and validate it."""
    path = _require_file(path)
    index_map = pd.read_csv(path)
    _check_columns(index_map.columns, INDEX_MAP_COLUMNS, path.name)
    validate_movie_index_map(index_map)
    return index_map[INDEX_MAP_COLUMNS].astype("int64")


def validate_movie_index_map(index_map: pd.DataFrame) -> None:
    """``item_index`` must be 0..n-1 and ``movieId`` unique, positive and increasing.

    Increasing ``movieId`` (as built by Phase 2) means that ordering by ``item_index`` is
    the same as ordering by ``movieId``, which the deterministic tie-break relies on.
    """
    if index_map.empty or index_map[INDEX_MAP_COLUMNS].isna().any().any():
        raise DataValidationError("movie index map: empty or with missing values")
    items = index_map["item_index"].to_numpy()
    movie_ids = index_map["movieId"].to_numpy()
    if not np.array_equal(items, np.arange(len(index_map))):
        raise DataValidationError("movie index map: item_index must be 0..n-1 in order")
    if (movie_ids <= 0).any() or (np.diff(movie_ids) <= 0).any():
        raise DataValidationError("movie index map: movieId must be positive, unique and increasing")


def build_rating_matrix(ratings: pd.DataFrame, index_map: pd.DataFrame) -> tuple[sparse.csr_array, np.ndarray]:
    """Sparse user x item matrix of explicit ratings. Returns ``(matrix, user_ids)``.

    Row ``r`` belongs to ``user_ids[r]`` (sorted ascending); column ``c`` is ``item_index c``.
    The ratings are validated first (positive IDs, half-star scale, no duplicated pair), so
    no cell can be summed twice. A movie that is not in the index map stops the build.
    """
    validate_training_ratings(ratings)
    item_of_movie = pd.Series(index_map["item_index"].to_numpy(), index=index_map["movieId"].to_numpy())
    items = ratings["movieId"].map(item_of_movie)
    if items.isna().any():
        unknown = sorted(ratings.loc[items.isna(), "movieId"].unique().tolist())[:10]
        raise DataValidationError(f"ratings contain movies that are not in the index map, e.g. {unknown}")
    user_ids, rows = np.unique(ratings["userId"].to_numpy(), return_inverse=True)
    matrix = sparse.csr_array(
        (ratings["rating"].to_numpy(dtype="float64"), (rows, items.to_numpy(dtype="int64"))),
        shape=(len(user_ids), len(index_map)),
    )
    return matrix, user_ids


def mean_centre_by_user(matrix: sparse.csr_array) -> tuple[sparse.csr_array, np.ndarray]:
    """Subtract each user's mean rating from that user's stored ratings.

    Returns ``(centred, means)``. Only stored (rated) cells change; empty cells stay empty.
    A user with no rating has mean 0 and contributes nothing.
    """
    matrix = sparse.csr_array(matrix)
    counts = np.diff(matrix.indptr)
    sums = np.asarray(matrix.sum(axis=1)).ravel()
    means = np.divide(sums, counts, out=np.zeros(len(counts)), where=counts > 0)
    centred = matrix.copy()
    centred.data = centred.data - np.repeat(means, counts)
    return centred, means


# ---------------------------------------------------------------------------
# 2. Item-item similarities and neighbour selection
# ---------------------------------------------------------------------------


def compute_item_neighbours(
    centred: sparse.csr_array, n_neighbours: int, block_size: int = BLOCK_SIZE
) -> sparse.csr_array:
    """Top-``n_neighbours`` positive adjusted-cosine neighbours of every item.

    Similarities are computed for ``block_size`` items at a time: the block's dense
    ``n_items x block_size`` similarity matrix is reduced to its top neighbours and then
    discarded, so the full ``n_items x n_items`` matrix is never held in memory.

    Row ``j`` of the result holds ``sim(j, i)`` for the kept neighbours ``i`` of ``j``.
    Kept: ``sim > 0`` and ``i != j``. Order: similarity descending, then smaller
    ``item_index`` (= smaller ``movieId``). Items with a zero norm (no rater deviates from
    their mean) have no defined similarity and get no neighbours.
    """
    _check_positive_int(n_neighbours, "n_neighbours")
    n_items = centred.shape[1]
    by_item = sparse.csr_array(centred.T)  # items x users
    by_user = sparse.csc_array(centred)  # users x items, fast column slices
    norms = np.sqrt(np.asarray(by_item.multiply(by_item).sum(axis=1)).ravel())

    rows, cols, values = [], [], []
    for start in range(0, n_items, block_size):
        stop = min(start + block_size, n_items)
        dots = (by_item @ by_user[:, start:stop]).toarray().T  # (block items) x (all items)
        denominators = np.outer(norms[start:stop], norms)
        sims = np.divide(dots, denominators, out=np.zeros_like(dots), where=denominators > 0)
        np.clip(sims, -1.0, 1.0, out=sims)  # guard against rounding just above 1
        sims[np.arange(stop - start), np.arange(start, stop)] = 0.0  # an item is not its own neighbour

        # Stable sort of -sim keeps equal similarities in item_index (= movieId) order.
        order = np.argsort(-sims, axis=1, kind="stable")[:, :n_neighbours]
        top = np.take_along_axis(sims, order, axis=1)
        keep = top > 0
        rows.append(np.nonzero(keep)[0] + start)
        cols.append(order[keep])
        values.append(top[keep])

    return sparse.csr_array(
        (np.concatenate(values), (np.concatenate(rows), np.concatenate(cols))), shape=(n_items, n_items)
    )


def _sorted_row(neighbours: sparse.csr_array, item: int) -> tuple[np.ndarray, np.ndarray]:
    """Neighbours of one item in (similarity desc, item_index asc) order."""
    start, stop = neighbours.indptr[item], neighbours.indptr[item + 1]
    items, sims = neighbours.indices[start:stop], neighbours.data[start:stop]
    order = np.lexsort((items, -sims))
    return items[order], sims[order]


# ---------------------------------------------------------------------------
# 3. The model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemCFModel:
    """A trained model: the neighbour matrix, the item_index -> movieId mapping and the scoring rule."""

    neighbours: sparse.csr_array  # item_index x item_index, row j = neighbours of j
    movie_ids: np.ndarray  # movie_ids[item_index] = movieId
    n_neighbours: int
    scoring: str = DEFAULT_SCORING

    def __post_init__(self):
        if self.scoring not in SCORING_METHODS:
            raise ValueError(f"scoring must be one of {SCORING_METHODS}, got {self.scoring!r}")

    @cached_property
    def item_of_movie(self) -> dict[int, int]:
        return {int(movie_id): item for item, movie_id in enumerate(self.movie_ids)}

    def similar_movies(self, movie_id: int) -> list[tuple[int, float]]:
        """The kept neighbours of a movie as ``(movieId, similarity)``, most similar first."""
        item = self.item_of_movie.get(int(movie_id))
        if item is None:
            return []
        items, sims = _sorted_row(self.neighbours, item)
        return [(int(self.movie_ids[i]), float(s)) for i, s in zip(items, sims, strict=True)]


def fit_item_cf(
    ratings: pd.DataFrame, index_map: pd.DataFrame, n_neighbours: int, scoring: str = DEFAULT_SCORING
) -> tuple[ItemCFModel, dict]:
    """Train the model on ``ratings`` (training data only). Returns ``(model, statistics)``."""
    matrix, user_ids = build_rating_matrix(ratings, index_map)
    centred, _ = mean_centre_by_user(matrix)
    neighbours = compute_item_neighbours(centred, n_neighbours)
    model = ItemCFModel(neighbours, index_map["movieId"].to_numpy(dtype="int64"), int(n_neighbours), scoring)
    return model, describe_model(model, matrix, centred, len(user_ids))


def with_scoring(model: ItemCFModel, scoring: str) -> ItemCFModel:
    """The same neighbours with another scoring rule (used to compare the rules in validation)."""
    return ItemCFModel(model.neighbours, model.movie_ids, model.n_neighbours, scoring)


def truncate_neighbours(model: ItemCFModel, n_neighbours: int) -> ItemCFModel:
    """Keep only the first ``n_neighbours`` of every item (same order as in training).

    Because neighbours are ranked by a fixed key, this gives exactly the model that
    training with the smaller ``n_neighbours`` would give, without recomputing similarities.
    """
    _check_positive_int(n_neighbours, "n_neighbours")
    if n_neighbours > model.n_neighbours:
        raise ValueError(f"cannot keep {n_neighbours} neighbours from a model with {model.n_neighbours}")
    rows, cols, values = [], [], []
    for item in range(model.neighbours.shape[0]):
        items, sims = _sorted_row(model.neighbours, item)
        rows.append(np.full(min(len(items), n_neighbours), item))
        cols.append(items[:n_neighbours])
        values.append(sims[:n_neighbours])
    shape = model.neighbours.shape
    neighbours = sparse.csr_array((np.concatenate(values), (np.concatenate(rows), np.concatenate(cols))), shape=shape)
    return ItemCFModel(neighbours, model.movie_ids, int(n_neighbours), model.scoring)


def describe_model(model: ItemCFModel, matrix: sparse.csr_array, centred: sparse.csr_array, n_users: int) -> dict:
    """Counts stored in the manifest (all derived from the training matrix)."""
    per_item = np.diff(model.neighbours.indptr)
    centred_abs = abs(centred)
    return {
        "users": int(n_users),
        "movies": int(matrix.shape[1]),
        "training_ratings": int(matrix.nnz),
        "users_with_constant_ratings": int((np.asarray(centred_abs.max(axis=1).toarray()).ravel() == 0).sum()),
        "movies_with_zero_norm": int((np.asarray(centred_abs.sum(axis=0)).ravel() == 0).sum()),
        "stored_similarities": int(model.neighbours.nnz),
        "neighbours_per_movie": {
            "min": int(per_item.min()),
            "median": float(np.median(per_item)),
            "max": int(per_item.max()),
            "movies_with_fewer_than_k": int((per_item < model.n_neighbours).sum()),
            "movies_without_neighbours": int((per_item == 0).sum()),
        },
        "similarity_values": {
            "min": round(float(model.neighbours.data.min()), 6),
            "median": round(float(np.median(model.neighbours.data)), 6),
            "max": round(float(model.neighbours.data.max()), 6),
        },
    }


# ---------------------------------------------------------------------------
# 4. Scoring and recommendation
# ---------------------------------------------------------------------------


def score_candidates(model: ItemCFModel, history: sparse.csr_array) -> np.ndarray:
    """Preference scores for every (user row, item) of ``history``, using ``model.scoring``.

    ``history`` is a users x items rating matrix (the users' own past ratings). Returns a
    dense ``users x items`` array with NaN where a score is not defined: the item is
    already rated, or none of its kept neighbours was rated by the user.

    * ``weighted_sum``: ``sum(sim(j, i) * (r_ui - mean_u))``. A ranking score, not a rating:
      it grows with the number of rated neighbours, is positive when the user rated the
      neighbours above their own mean and negative when below.
    * ``weighted_average``: ``mean_u + sum(sim * (r_ui - mean_u)) / sum(|sim|)``. With
      positive similarities it is a weighted average of the user's ratings (0.5-5.0).
    """
    history = sparse.csr_array(history)
    centred, means = mean_centre_by_user(history)
    rated = history.copy()
    rated.data = np.ones_like(rated.data)
    transposed = sparse.csr_array(model.neighbours.T)  # column j = neighbours of j
    numerators = (centred @ transposed).toarray()  # sum_i sim(j, i) * c_ui
    weights = (rated @ abs(transposed)).toarray()  # sum_i |sim(j, i)| over rated neighbours
    supported = weights > 0
    if model.scoring == "weighted_sum":
        values = numerators
    else:
        values = means[:, None] + numerators / np.where(supported, weights, 1.0)
    scores = np.where(supported, values, np.nan)
    scores[rated.toarray() > 0] = np.nan  # never recommend a movie the user has rated
    return scores


def top_n_from_scores(scores: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Best ``n`` items per row: score descending, ties by smaller item_index (= movieId).

    Returns ``(items, values)`` of shape ``rows x n``; positions without a scored
    candidate hold item -1 and value NaN (the list is shorter than ``n``).
    """
    filled = np.where(np.isnan(scores), -np.inf, scores)
    order = np.argsort(-filled, axis=1, kind="stable")[:, :n]
    values = np.take_along_axis(scores, order, axis=1)
    return np.where(np.isnan(values), -1, order), values


def recommend_for_history(model: ItemCFModel, history: sparse.csr_array, n: int) -> list[list[tuple[int, float]]]:
    """Top-``n`` ``(movieId, score)`` lists for every row of a users x items matrix."""
    _check_positive_int(n, "n")
    items, values = top_n_from_scores(score_candidates(model, history), n)
    return [
        [(int(model.movie_ids[i]), float(v)) for i, v in zip(row_items, row_values, strict=True) if i >= 0]
        for row_items, row_values in zip(items, values, strict=True)
    ]


def recommend_movies(model: ItemCFModel, user_ratings: Mapping[int, float], n: int) -> list[tuple[int, float]]:
    """Recommend ``n`` movies for one user from their ``{movieId: rating}`` history.

    * The rated movies are excluded; every other catalogue movie (including watchlist
      movies, which the ML component does not know about) is a candidate.
    * Movies outside the model's catalogue are ignored (they have no similarities).
    * Ratings must be on the MovieLens scale (0.5-5.0, half stars); otherwise ValueError.
    * An empty or unusable history gives an empty list: no score is invented.

    Returns ``(movieId, score)`` pairs, best first. With the default ``weighted_sum``
    scoring, ``score`` only orders the movies for this user; it is not a predicted rating.
    """
    _check_positive_int(n, "n")
    known = {}
    for movie_id, rating in user_ratings.items():
        if float(rating) not in VALID_RATINGS:
            raise ValueError(f"rating {rating!r} for movie {movie_id!r} is not on the 0.5-5.0 half-star scale")
        item = model.item_of_movie.get(int(movie_id))
        if item is not None:
            known[item] = float(rating)
    if not known:
        return []
    history = sparse.csr_array(
        (list(known.values()), ([0] * len(known), list(known.keys()))), shape=(1, len(model.movie_ids))
    )
    return recommend_for_history(model, history, n)[0]


def _check_positive_int(value, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")


# ---------------------------------------------------------------------------
# 5. Persistence
# ---------------------------------------------------------------------------


def neighbours_fingerprint(neighbours: sparse.csr_array) -> str:
    """SHA-256 of the matrix contents (independent of the .npz container's metadata)."""
    matrix = sparse.csr_array(neighbours, copy=True)
    matrix.sort_indices()
    digest = hashlib.sha256()
    for array, dtype in [
        (np.array(matrix.shape), "int64"),
        (matrix.indptr, "int64"),
        (matrix.indices, "int64"),
        (matrix.data, "float64"),
    ]:
        digest.update(np.ascontiguousarray(array, dtype=dtype).tobytes())
    return digest.hexdigest()


def _refuse_to_overwrite(output_dir: Path, overwrite: bool) -> None:
    existing = [str(Path(output_dir) / name) for name in OUTPUT_FILES.values() if (Path(output_dir) / name).exists()]
    if existing and not overwrite:
        raise FileExistsError(f"Output file(s) already exist: {existing}. Use --overwrite to replace them.")


def write_cf_model(model: ItemCFModel, manifest: dict, output_dir: Path, overwrite: bool = False) -> dict:
    """Write the neighbour matrix and its manifest; refuse to overwrite unless requested."""
    output_dir = Path(output_dir)
    _refuse_to_overwrite(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / OUTPUT_FILES["neighbours"]
    sparse.save_npz(path, model.neighbours, compressed=True)
    manifest = {
        **manifest,
        "output": {
            "file": path.name,
            "shape": list(model.neighbours.shape),
            "stored_similarities": int(model.neighbours.nnz),
            "sha256": sha256_of(path),
            "content_sha256": neighbours_fingerprint(model.neighbours),
        },
    }
    with open(output_dir / OUTPUT_FILES["manifest"], "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, default=_json_default)
    return manifest


def load_cf_model(
    model_dir: Path = DEFAULT_OUTPUT_DIR, processed_dir: Path = DEFAULT_PROCESSED_DIR
) -> tuple[ItemCFModel, dict]:
    """Load a trained model without recomputing anything. Returns ``(model, manifest)``.

    The neighbour file must match the hash in the manifest, and the index map must be the
    one the model was trained with (same SHA-256). The matrix is checked again, so a
    missing, edited or inconsistent artefact is reported, never used.
    """
    model_dir, processed_dir = Path(model_dir), Path(processed_dir)
    manifest_path = model_dir / OUTPUT_FILES["manifest"]
    npz_path = model_dir / OUTPUT_FILES["neighbours"]
    index_map_path = processed_dir / DATA_FILES["index_map"]
    for path in (manifest_path, npz_path):
        if not path.is_file():
            raise FileNotFoundError(
                f"CF model file not found: '{path}'. Train it with: python -m src.collaborative_filtering"
            )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        algorithm = manifest["model"]["algorithm"]
        n_neighbours = int(manifest["model"]["neighbours"])
        scoring = manifest["model"]["scoring"]
        expected_hash = manifest["output"]["sha256"]
        index_map_hash = manifest["source"]["index_map_file_sha256"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise DataValidationError(f"{manifest_path.name} is malformed: {error!r}") from error
    if algorithm != ALGORITHM or scoring not in SCORING_METHODS:
        raise DataValidationError(f"{manifest_path.name}: unsupported algorithm '{algorithm}' / scoring '{scoring}'")
    if sha256_of(npz_path) != expected_hash:
        raise DataValidationError(f"{npz_path.name} does not match the hash in {manifest_path.name}; retrain it.")
    _verify_input_hash(_require_file(index_map_path), index_map_hash)

    index_map = load_movie_index_map(index_map_path)
    neighbours = sparse.csr_array(sparse.load_npz(npz_path))
    problems = validate_neighbours(neighbours, len(index_map), n_neighbours)
    if problems:
        raise DataValidationError(f"{npz_path.name} failed validation: {problems}")
    return ItemCFModel(neighbours, index_map["movieId"].to_numpy(dtype="int64"), n_neighbours, scoring), manifest


def validate_neighbours(neighbours: sparse.csr_array, n_items: int, n_neighbours: int) -> list[str]:
    """Return the names of the failed checks (empty list = valid)."""
    data = neighbours.data
    checks = {
        "square_shape_matches_index_map": neighbours.shape == (n_items, n_items),
        "similarities_finite_and_in_0_1": bool(np.isfinite(data).all() and (data > 0).all() and (data <= 1).all()),
        "at_most_k_neighbours_per_movie": bool((np.diff(neighbours.indptr) <= n_neighbours).all()),
        "no_movie_is_its_own_neighbour": bool((neighbours.diagonal() == 0).all())
        if neighbours.shape[0] == neighbours.shape[1]
        else False,
    }
    return [name for name, passed in checks.items() if not passed]


# ---------------------------------------------------------------------------
# 6. Training pipeline
# ---------------------------------------------------------------------------


def load_verified_training_inputs(processed_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Training ratings + index map, both checked against ``dataset_manifest.json``.

    Returns ``(train, index_map, source)``. The index map's movies must be exactly the
    catalogue movies. There is no way to request the test file from this function.
    """
    processed_dir = Path(processed_dir)
    dataset = _read_dataset_manifest(processed_dir)
    paths = {key: _require_file(processed_dir / DATA_FILES[key]) for key in ("train", "catalogue", "index_map")}
    try:
        expected = {key: dataset["outputs"][key]["sha256"] for key in paths}
    except KeyError as error:
        raise DataValidationError(f"{DATA_FILES['manifest']} is malformed: {error!r}") from error
    hashes = {key: _verify_input_hash(path, expected[key]) for key, path in paths.items()}

    train = load_training_ratings(paths["train"])
    if len(train) != dataset["counts"]["train_ratings"]:
        raise DataValidationError("number of training ratings differs from the dataset manifest")
    index_map = load_movie_index_map(paths["index_map"])
    catalogue_ids = load_catalogue_movie_ids(paths["catalogue"])
    if set(index_map["movieId"].tolist()) != set(catalogue_ids.tolist()):
        raise DataValidationError("the movie index map and the catalogue contain different movies")

    source = {
        "dataset": dataset.get("dataset", {}).get("name"),
        "data_pipeline_version": dataset.get("pipeline", {}).get("version"),
        "training_file": DATA_FILES["train"],
        "training_file_sha256": hashes["train"],
        "catalogue_file_sha256": hashes["catalogue"],
        "index_map_file": DATA_FILES["index_map"],
        "index_map_file_sha256": hashes["index_map"],
        "test_file_used": False,
    }
    return train, index_map, source


def run_cf_training(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    n_neighbours: int = DEFAULT_NEIGHBOURS,
    overwrite: bool = False,
    scoring: str = DEFAULT_SCORING,
    validation_results: Path | None = None,
) -> dict:
    """Train on the complete ``ratings_train.csv`` and write the model. Returns the manifest.

    If the validation results exist, their hash and selected configuration are recorded,
    so the manifest shows whether this model is the configuration chosen on validation.
    """
    _check_positive_int(n_neighbours, "n_neighbours")
    if scoring not in SCORING_METHODS:
        raise ValueError(f"scoring must be one of {SCORING_METHODS}, got {scoring!r}")
    _refuse_to_overwrite(output_dir, overwrite)  # before the expensive work
    started = time.perf_counter()
    logger.info("Loading and verifying the training inputs")
    train, index_map, source = load_verified_training_inputs(processed_dir)
    loaded = time.perf_counter()

    logger.info("Training item-based CF on %d ratings (k = %d, %s)", len(train), n_neighbours, scoring)
    model, stats = fit_item_cf(train, index_map, n_neighbours, scoring)
    del train
    trained = time.perf_counter()

    manifest = {
        "model": {
            "name": "AuraCinema item-based collaborative filtering",
            "version": MODEL_VERSION,
            "script": "ml/src/collaborative_filtering.py",
            "algorithm": ALGORITHM,
            "similarity": "adjusted cosine: cosine of user-mean-centred item vectors (unrated = 0)",
            "neighbours": int(n_neighbours),
            "neighbour_rule": "top-k positive similarities per movie; ties by smaller movieId; no self",
            "scoring": scoring,
            "scoring_formula": {
                "weighted_sum": "sum(sim(j,i) * (r_ui - mean_u)) over the rated neighbours of j",
                "weighted_average": "mean_u + sum(sim(j,i) * (r_ui - mean_u)) / sum(|sim(j,i)|)",
            }[scoring],
            "score_meaning": "preference ranking score, not a predicted rating"
            if scoring == "weighted_sum"
            else "estimated rating, within 0.5-5.0 by construction",
            "unsupported_candidates": "no score (not recommended); no popularity fallback",
            "identifier": "MovieLens movieId (item_index is internal only)",
            "random_seed": None,  # fully deterministic
        },
        "source": source,
        "validation": _describe_validation(Path(validation_results), n_neighbours, scoring)
        if validation_results is not None
        else None,
        "counts": stats,
        "run": {
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "load_seconds": round(loaded - started, 1),
            "training_seconds": round(trained - loaded, 1),
        },
    }
    manifest = write_cf_model(model, manifest, output_dir, overwrite)
    logger.info("Finished in %.1f s; wrote %s", time.perf_counter() - started, Path(output_dir))
    return manifest


def _describe_validation(path: Path, n_neighbours: int, scoring: str) -> dict | None:
    """Link to the validation run that selected the configuration (None if it was not run)."""
    if not path.is_file():
        return None
    try:
        results = json.loads(path.read_text(encoding="utf-8"))
        selected = {"neighbours": int(results["selected_neighbours"]), "scoring": results["selected_scoring"]}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise DataValidationError(f"{path.name} is malformed: {error!r}") from error
    return {
        "file": path.name,
        "sha256": sha256_of(path),
        "selected": selected,
        "model_matches_selected_configuration": selected == {"neighbours": int(n_neighbours), "scoring": scoring},
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the AuraCinema item-based CF model (training data only).")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--neighbours", type=int, default=DEFAULT_NEIGHBOURS, help="neighbours kept per movie (k)")
    parser.add_argument("--scoring", choices=SCORING_METHODS, default=DEFAULT_SCORING)
    parser.add_argument("--validation-results", type=Path, default=DEFAULT_VALIDATION_RESULTS)
    parser.add_argument("--overwrite", action="store_true", help="replace outputs from a previous run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    try:
        manifest = run_cf_training(
            args.processed_dir,
            args.output_dir,
            args.neighbours,
            overwrite=args.overwrite,
            scoring=args.scoring,
            validation_results=args.validation_results,
        )
    except (FileNotFoundError, FileExistsError, DataValidationError, ValueError) as error:
        logger.error("%s", error)
        raise SystemExit(1) from error
    logger.info("Model counts: %s", json.dumps(manifest["counts"]))


if __name__ == "__main__":
    main()
