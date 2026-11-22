"""Tests for item-based collaborative filtering (ml/src/collaborative_filtering.py).

Only the tests needed to protect each distinct behaviour are kept:
* hand-checkable examples for the mathematics (matrix, centring, similarity, neighbours, score);
* input handling of the public recommendation function;
* persistence, integrity and data-leakage checks on the shared ``prepared_models`` fixture
  (conftest.py), copying files before any change.
Validation of the rating records themselves (scale, duplicates, missing values) is the
Phase 4 function ``validate_training_ratings``, already tested in test_popularity_baseline.py.
"""

import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest
from src.collaborative_filtering import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    OUTPUT_FILES,
    build_rating_matrix,
    fit_item_cf,
    load_cf_model,
    mean_centre_by_user,
    neighbours_fingerprint,
    recommend_movies,
    run_cf_training,
    truncate_neighbours,
    with_scoring,
)
from src.prepare_data import DataValidationError

# Example A. Every user has mean 3, so the centred values are easy to check by hand:
#   c(10) = [ 2, 1, 0, -1]   c(20) = [2, -1, 1, 0]   c(30) = [-2, 0, -1, 1]   c(40) = [-2, 0, 0, 0]
# sim(10,20) = 3/6 = 0.5; sim(30,40) = 4/(sqrt(6)*2) = 0.8165; sim(10,30) = sim(20,30) = -5/6;
# sim(10,40) = sim(20,40) = -0.8165. Movie 290001 is rated only at the user's mean (norm 0).
RATINGS_A = [
    (1, 10, 5.0), (1, 20, 5.0), (1, 30, 1.0), (1, 40, 1.0),
    (2, 10, 4.0), (2, 20, 2.0),
    (3, 20, 4.0), (3, 30, 2.0), (3, 290001, 3.0),
    (4, 10, 2.0), (4, 30, 4.0),
]  # fmt: skip
MOVIES_A = [10, 20, 30, 40, 290001]


def ratings_frame(rows):
    return pd.DataFrame([(u, m, r, 1000 + i) for i, (u, m, r) in enumerate(rows)],
                        columns=["userId", "movieId", "rating", "timestamp"])  # fmt: skip


def index_map_for(movie_ids):
    return pd.DataFrame({"item_index": range(len(movie_ids)), "movieId": sorted(movie_ids)})


@pytest.fixture
def model_a():
    model, _ = fit_item_cf(ratings_frame(RATINGS_A), index_map_for(MOVIES_A), n_neighbours=2)
    return model


def copy_of(folder, tmp_path):
    return shutil.copytree(folder, tmp_path / folder.name)


# ---------------------------------------------------------------------------
# Matrix construction and mean-centring
# ---------------------------------------------------------------------------


def test_rating_matrix_uses_the_index_map_and_is_mean_centred_by_user():
    matrix, user_ids = build_rating_matrix(ratings_frame(RATINGS_A), index_map_for(MOVIES_A))
    centred, means = mean_centre_by_user(matrix)
    assert matrix.shape == (4, 5) and matrix.nnz == len(RATINGS_A)
    assert user_ids.tolist() == [1, 2, 3, 4]
    assert matrix[2, 4] == 3.0  # user 3, movieId 290001 -> item_index 4
    assert means.tolist() == [3.0, 3.0, 3.0, 3.0]
    assert centred.toarray()[:, 0].tolist() == [2.0, 1.0, 0.0, -1.0]  # c(10)
    assert centred[0, 3] == -2.0 and centred.nnz == matrix.nnz  # unrated cells stay empty


def test_ratings_for_a_movie_outside_the_index_map_are_rejected():
    with pytest.raises(DataValidationError, match="not in the index map"):
        build_rating_matrix(ratings_frame(RATINGS_A), index_map_for([10, 20, 30, 40]))


# ---------------------------------------------------------------------------
# Similarity and neighbour selection
# ---------------------------------------------------------------------------


def test_adjusted_cosine_keeps_only_positive_neighbours(model_a):
    assert model_a.similar_movies(10) == [(20, pytest.approx(0.5))]  # 30 and 40 are negative
    assert model_a.similar_movies(30) == [(40, pytest.approx(4 / (math.sqrt(6) * 2)))]
    assert model_a.similar_movies(290001) == []  # zero norm: no usable similarity
    assert model_a.similar_movies(999) == []  # unknown movie


def test_neighbour_ties_are_broken_by_movie_id_and_k_is_respected():
    # Movies 1, 2 and 3 have identical centred columns (sim = 1); movie 4 is opposite (sim = -1).
    rows = [(1, 1, 5.0), (1, 2, 5.0), (1, 3, 5.0), (1, 4, 1.0), (2, 1, 1.0), (2, 2, 1.0), (2, 3, 1.0), (2, 4, 5.0)]
    train, index_map = ratings_frame(rows), index_map_for([1, 2, 3, 4])
    k1, _ = fit_item_cf(train, index_map, n_neighbours=1)
    k2, _ = fit_item_cf(train, index_map, n_neighbours=2)
    assert [k1.similar_movies(m)[0][0] for m in (1, 2, 3)] == [2, 1, 1]
    assert [m for m, _ in k2.similar_movies(3)] == [1, 2]
    assert k2.similar_movies(4) == []
    # Truncating the larger model gives exactly the smaller one (used by the validation).
    assert neighbours_fingerprint(truncate_neighbours(k2, 1).neighbours) == neighbours_fingerprint(k1.neighbours)


# ---------------------------------------------------------------------------
# Scoring and the recommendation interface
# ---------------------------------------------------------------------------


def test_scores_match_the_hand_calculation(model_a):
    # History {10: 4, 30: 2}, mean 3; deviations +1 (movie 10) and -1 (movie 30).
    # Candidate 20 has rated neighbour 10 (sim 0.5); candidate 40 has rated neighbour 30 (sim 0.8165).
    # 290001 has no evidence; rated movies 10 and 30 are excluded; original movieIds are returned.
    s = 4 / (math.sqrt(6) * 2)
    # weighted_sum (final model): 0.5 * (+1) = 0.5 and 0.8165 * (-1) = -0.8165.
    assert recommend_movies(model_a, {10: 4.0, 30: 2.0}, n=10) == [(20, pytest.approx(0.5)), (40, pytest.approx(-s))]
    assert recommend_movies(model_a, {10: 4.0, 30: 2.0}, n=1) == [(20, pytest.approx(0.5))]
    # weighted_average (rejected variant): 3 + 0.5 * 1 / 0.5 = 4 and 3 + s * (-1) / s = 2.
    average = with_scoring(model_a, "weighted_average")
    assert recommend_movies(average, {10: 4.0, 30: 2.0}, n=10) == [(20, pytest.approx(4.0)), (40, pytest.approx(2.0))]


def test_recommend_handles_unknown_empty_and_invalid_input(model_a):
    expected = recommend_movies(model_a, {10: 4.0, 30: 2.0}, n=10)
    assert recommend_movies(model_a, {10: 4.0, 30: 2.0, 999: 5.0}, n=10) == expected  # unknown id ignored
    assert recommend_movies(model_a, {}, n=10) == []  # no history -> no invented score
    with pytest.raises(ValueError, match="half-star"):
        recommend_movies(model_a, {10: 4.2}, n=10)
    with pytest.raises(ValueError, match="positive integer"):
        recommend_movies(model_a, {10: 4.0}, n=0)


# ---------------------------------------------------------------------------
# Persistence, integrity and reproducibility
# ---------------------------------------------------------------------------


def test_saved_model_loads_and_equals_a_fresh_training(prepared_models):
    model, manifest = load_cf_model(prepared_models.models, prepared_models.processed)
    train = pd.read_csv(prepared_models.processed / "ratings_train.csv")
    index_map = pd.read_csv(prepared_models.processed / "movie_index_map.csv")
    fresh, _ = fit_item_cf(train, index_map, n_neighbours=3)
    assert neighbours_fingerprint(model.neighbours) == neighbours_fingerprint(fresh.neighbours)
    assert manifest["output"]["content_sha256"] == neighbours_fingerprint(fresh.neighbours)
    assert manifest["model"]["neighbours"] == 3 and manifest["source"]["test_file_used"] is False
    assert model.scoring == manifest["model"]["scoring"] == "weighted_sum"


def test_existing_model_is_not_overwritten_by_default(prepared_models, tmp_path):
    models = copy_of(prepared_models.models, tmp_path)
    before = (models / OUTPUT_FILES["manifest"]).read_bytes()
    with pytest.raises(FileExistsError, match="--overwrite"):
        run_cf_training(prepared_models.processed, models, n_neighbours=3)
    assert (models / OUTPUT_FILES["manifest"]).read_bytes() == before


@pytest.mark.parametrize(
    "corrupt, error",
    [
        (lambda d: (d / OUTPUT_FILES["neighbours"]).unlink(), FileNotFoundError),
        (lambda d: (d / OUTPUT_FILES["neighbours"]).write_bytes(b"not a model"), DataValidationError),
        (lambda d: (d / OUTPUT_FILES["manifest"]).write_text("{not json", encoding="utf-8"), DataValidationError),
    ],
)
def test_missing_or_corrupted_artefacts_are_rejected(prepared_models, tmp_path, corrupt, error):
    models = copy_of(prepared_models.models, tmp_path)
    corrupt(models)
    with pytest.raises(error):
        load_cf_model(models, prepared_models.processed)


def test_index_map_that_does_not_belong_to_the_model_is_rejected(prepared_models, tmp_path):
    processed = copy_of(prepared_models.processed, tmp_path)
    path = processed / "movie_index_map.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="SHA-256 recorded in cf_model_manifest.json"):
        load_cf_model(prepared_models.models, processed)


def test_training_file_changed_after_preparation_is_rejected(prepared_models, tmp_path):
    processed = copy_of(prepared_models.processed, tmp_path)
    path = processed / "ratings_train.csv"
    path.write_text(path.read_text(encoding="utf-8") + "999,1,4.0,1000000001\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="SHA-256"):
        run_cf_training(processed, tmp_path / "out", n_neighbours=3)


# ---------------------------------------------------------------------------
# Data leakage
# ---------------------------------------------------------------------------


def test_test_ratings_cannot_change_the_model_but_training_ratings_do(prepared_models, tmp_path):
    expected = prepared_models.cf_manifest["output"]["content_sha256"]
    processed = copy_of(prepared_models.processed, tmp_path)
    test_path = processed / "ratings_test.csv"
    pd.read_csv(test_path).assign(rating=5.0).to_csv(test_path, index=False)  # every test rating changed
    assert run_cf_training(processed, tmp_path / "changed", n_neighbours=3)["output"]["content_sha256"] == expected
    test_path.unlink()  # the test file is not even needed
    assert run_cf_training(processed, tmp_path / "deleted", n_neighbours=3)["output"]["content_sha256"] == expected

    # Control: a change in the TRAINING ratings does change the model, so the checks above can fail.
    train = pd.read_csv(processed / "ratings_train.csv")
    index_map = pd.read_csv(processed / "movie_index_map.csv")
    changed = train.assign(rating=np.where(train.index < 10, 0.5, train["rating"]))
    assert neighbours_fingerprint(fit_item_cf(changed, index_map, 3)[0].neighbours) != expected


REAL_MODEL_PRESENT = (DEFAULT_OUTPUT_DIR / OUTPUT_FILES["manifest"]).is_file()


@pytest.mark.skipif(not REAL_MODEL_PRESENT, reason="real CF model not trained on this machine")
def test_real_model_is_consistent_with_the_prepared_dataset():
    # Read-only: loads the real artefacts, never writes.
    model, manifest = load_cf_model(DEFAULT_OUTPUT_DIR, DEFAULT_PROCESSED_DIR)
    dataset = json.loads((DEFAULT_PROCESSED_DIR / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"]["training_file_sha256"] == dataset["outputs"]["train"]["sha256"]
    assert manifest["counts"]["training_ratings"] == dataset["counts"]["train_ratings"]
    assert model.neighbours.shape == (5068, 5068)
