"""Tests for the popularity baseline (ml/src/popularity_baseline.py).

Structure:
* ``train`` / ``ranking``: tiny hand-checkable data, rebuilt for every test (some tests edit it).
* ``prepared``: the real data-preparation pipeline and the baseline run ONCE per module on
  synthetic data. Tests may only READ these shared files.
* Tests that modify or delete files first copy them into their own ``tmp_path``
  (``copy_of``), so they can never affect another test.
The last test reads the real artefacts and is skipped when they have not been generated.
"""

import json
import shutil
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import make_links, make_movies, write_dataset
from src.popularity_baseline import (
    ALGORITHM,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROCESSED_DIR,
    OUTPUT_FILES,
    RANKING_COLUMNS,
    build_popularity_ranking,
    load_popularity_baseline,
    load_training_ratings,
    run_popularity_baseline,
    top_n_popular_movies,
    validate_popularity_ranking,
)
from src.prepare_data import DataValidationError, PreparationConfig, run_pipeline, sha256_of

CATALOGUE = [10, 20, 30, 40]


def ratings_frame(rows):
    return pd.DataFrame(rows, columns=["userId", "movieId", "rating", "timestamp"])


def copy_of(folder, tmp_path):
    """Private copy of a shared folder, for tests that change files."""
    return shutil.copytree(folder, tmp_path / folder.name)


@pytest.fixture
def train():
    """Movie 20 has 3 ratings, 10 and 30 have 2 (a tie), 40 has 1."""
    return ratings_frame(
        [
            (1, 10, 4.0, 100),
            (2, 10, 5.0, 101),
            (1, 20, 1.0, 102),
            (2, 20, 2.0, 103),
            (3, 20, 4.0, 104),
            (2, 30, 3.0, 105),
            (3, 30, 3.5, 106),
            (3, 40, 0.5, 107),
        ]
    )


@pytest.fixture
def ranking(train):
    return build_popularity_ranking(train, CATALOGUE)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    """Pipeline outputs + one baseline, generated once and shared read-only.

    Each of 8 users rates 5-7 movies in a rotated order, so every movie keeps training
    ratings after the chronological split.
    """
    root = tmp_path_factory.mktemp("prepared")
    movies = [1, 2, 3, 4, 5, 6, 290001]
    rows = []
    for user in range(1, 9):
        rotated = movies[user % 7 :] + movies[: user % 7]
        for i, movie in enumerate(rotated[: 5 + user % 3]):
            rating = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0][(user * 3 + i) % 10]
            rows.append((user, movie, rating, 1_000_000_000 + user * 1000 + i * 10))
    raw = write_dataset(root / "raw", ratings_frame(rows), make_movies(), make_links())
    config = PreparationConfig(top_n_movies=10, genre_floor_movies=0, min_user_ratings=5, test_fraction=0.2)
    processed = root / "processed"
    run_pipeline(raw, processed, root / "data_quality_report.json", config)
    baseline = root / "baseline"
    manifest = run_popularity_baseline(processed, baseline)
    return SimpleNamespace(processed=processed, baseline=baseline, manifest=manifest)


# ---------------------------------------------------------------------------
# Statistics and ranking
# ---------------------------------------------------------------------------


def test_counts_averages_scores_and_ranks_are_correct(ranking):
    by_movie = ranking.set_index("movieId")
    assert by_movie["rating_count"].to_dict() == {10: 2, 20: 3, 30: 2, 40: 1}
    assert by_movie.loc[10, "average_rating"] == 4.5
    assert by_movie.loc[20, "average_rating"] == pytest.approx(7.0 / 3.0, abs=1e-12)
    assert (ranking["popularity_score"] == ranking["rating_count"]).all()
    assert ranking["movieId"].tolist() == [20, 10, 30, 40]
    assert ranking["rank"].tolist() == [1, 2, 3, 4]
    assert list(ranking.columns) == RANKING_COLUMNS  # no item_index


def test_ties_are_broken_by_smaller_movie_id_regardless_of_row_order(train, ranking):
    for seed in range(3):
        shuffled = train.sample(frac=1, random_state=seed).reset_index(drop=True)
        pd.testing.assert_frame_equal(build_popularity_ranking(shuffled, CATALOGUE[::-1]), ranking)


def test_average_rating_does_not_influence_the_ranking():
    # Movie 2 has a far higher average but fewer ratings, so it must rank lower.
    rows = [(u, 1, 0.5, u) for u in range(1, 4)] + [(u, 2, 5.0, u) for u in range(1, 3)]
    assert build_popularity_ranking(ratings_frame(rows), [1, 2])["movieId"].tolist() == [1, 2]


def test_minimum_activity_scale_bounds_and_large_ids():
    rows = [(1, 290001, 5.0, 1), (1, 7, 0.5, 2), (2, 7, 0.5, 3)]
    by_movie = build_popularity_ranking(ratings_frame(rows), [7, 290001]).set_index("movieId")
    assert by_movie.loc[290001, "rating_count"] == 1  # a single training rating is still ranked
    assert by_movie.loc[290001, "average_rating"] == 5.0
    assert by_movie.loc[7, "average_rating"] == 0.5


# ---------------------------------------------------------------------------
# Input validation: structural problems stop the calculation
# ---------------------------------------------------------------------------


def test_empty_training_data_raises():
    with pytest.raises(DataValidationError, match="empty"):
        build_popularity_ranking(ratings_frame([]), CATALOGUE)


@pytest.mark.parametrize(
    "change",
    [
        lambda df: df.drop(columns="timestamp"),
        lambda df: df.assign(item_index=0),
    ],
)
def test_missing_or_unexpected_columns_raise(train, change):
    with pytest.raises(DataValidationError, match="unexpected structure"):
        build_popularity_ranking(change(train), CATALOGUE)


@pytest.mark.parametrize(
    "column, value",
    [
        ("rating", 0.0),
        ("rating", 5.5),
        ("rating", 3.3),
        ("rating", np.nan),
        ("movieId", np.nan),
        ("movieId", 0),
        ("userId", -1),
    ],
)
def test_invalid_values_raise(train, column, value):
    train[column] = train[column].astype("float64")
    train.loc[0, column] = value
    with pytest.raises(DataValidationError):
        build_popularity_ranking(train, CATALOGUE)


def test_duplicate_records_raise(train):
    with pytest.raises(DataValidationError, match="duplicated"):
        build_popularity_ranking(pd.concat([train, train.head(1)], ignore_index=True), CATALOGUE)


@pytest.mark.parametrize(
    "catalogue, message",
    [
        (CATALOGUE + [99], "no training rating"),  # catalogue movie without training ratings
        ([10, 20, 30], "not in the catalogue"),  # training movie outside the catalogue
        ([10, 20, 30, 40, 40], "duplicated movieId"),  # duplicate catalogue id
    ],
)
def test_catalogue_mismatches_raise(train, catalogue, message):
    with pytest.raises(DataValidationError, match=message):
        build_popularity_ranking(train, catalogue)


@pytest.mark.parametrize(
    "content",
    [
        "userId,movieId,rating,timestamp\n1,10,4.0,100\n2,,5.0,101\n",  # missing value
        "userId,movieId,rating,timestamp\n1,10,four,100\n",  # non-numeric value
    ],
)
def test_malformed_training_file_raises(tmp_path, content):
    path = tmp_path / "ratings_train.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DataValidationError):
        load_training_ratings(path)


# ---------------------------------------------------------------------------
# Validation of a ranking
# ---------------------------------------------------------------------------


def test_valid_ranking_passes_every_check(ranking):
    assert all(validate_popularity_ranking(ranking, CATALOGUE, expected_total_ratings=8).values())


@pytest.mark.parametrize(
    "corrupt, failed_check",
    [
        (lambda r: r.assign(rank=[1, 1, 3, 4]), "ranks_are_1_to_n_without_duplicates"),
        (
            lambda r: r.iloc[[0, 2, 1, 3]].reset_index(drop=True).assign(rank=[1, 2, 3, 4]),
            "order_is_count_desc_then_movie_id_asc",
        ),
        (lambda r: r.assign(popularity_score=r["popularity_score"] + 1), "popularity_score_equals_rating_count"),
        (
            lambda r: r.assign(rating_count=[3, 2, 2, 0], popularity_score=[3, 2, 2, 0]),
            "rating_counts_positive_integers",
        ),
        (lambda r: r.assign(average_rating=[5.5, 4.5, 3.25, 0.5]), "average_rating_within_scale"),
        (lambda r: r.assign(average_rating=[np.inf, 4.5, 3.25, 0.5]), "no_missing_or_non_finite_values"),
        (lambda r: r.assign(popularity_score=[3, 2, None, 1]), "no_missing_or_non_finite_values"),
        (lambda r: r.assign(movieId=[20, 10, 10, 40]), "movie_ids_unique"),
    ],
)
def test_corrupted_ranking_is_detected(ranking, corrupt, failed_check):
    assert validate_popularity_ranking(corrupt(ranking), CATALOGUE)[failed_check] is False


# ---------------------------------------------------------------------------
# Top-N interface
# ---------------------------------------------------------------------------


def test_top_n_returns_movie_id_score_pairs_in_rank_order(ranking):
    assert top_n_popular_movies(ranking, 2) == [(20, 3.0), (10, 2.0)]
    assert len(top_n_popular_movies(ranking, 100)) == 4  # n larger than the catalogue


@pytest.mark.parametrize("n", [0, -1, 1.5, True, "3"])
def test_top_n_rejects_invalid_n(ranking, n):
    with pytest.raises(ValueError, match="positive integer"):
        top_n_popular_movies(ranking, n)


def test_excluded_movies_are_skipped_and_the_list_is_refilled(ranking):
    assert top_n_popular_movies(ranking, 2, exclude_movie_ids=[20, 999]) == [(10, 2.0), (30, 2.0)]
    assert top_n_popular_movies(ranking, 2, exclude_movie_ids=CATALOGUE) == []


# ---------------------------------------------------------------------------
# Data leakage: the test set must never influence the baseline
# ---------------------------------------------------------------------------


def test_modified_test_ratings_do_not_change_the_baseline(prepared, tmp_path):
    processed = copy_of(prepared.processed, tmp_path)
    test_path = processed / "ratings_test.csv"
    test = pd.read_csv(test_path)
    extra = pd.DataFrame({"userId": range(1000, 1500), "movieId": 290001, "rating": 5.0, "timestamp": 2_000_000_000})
    pd.concat([test.assign(rating=0.5), extra], ignore_index=True).to_csv(test_path, index=False)

    after = run_popularity_baseline(processed, tmp_path / "after")
    assert (prepared.baseline / OUTPUT_FILES["ranking"]).read_bytes() == (
        tmp_path / "after" / OUTPUT_FILES["ranking"]
    ).read_bytes()
    assert after["distribution"] == prepared.manifest["distribution"]


def test_baseline_runs_without_the_test_file(prepared, tmp_path):
    processed = copy_of(prepared.processed, tmp_path)
    (processed / "ratings_test.csv").unlink()
    without_file = run_popularity_baseline(processed, tmp_path / "out")
    assert without_file["output"]["sha256"] == prepared.manifest["output"]["sha256"]
    assert without_file["source"]["test_file_used"] is False


def test_leakage_check_is_able_to_detect_merged_test_ratings(train, ranking):
    # Control test: merging test ratings into training WOULD change the result, so the
    # identical outputs above are real evidence that test data is not used.
    test = ratings_frame([(4, 40, 5.0, 200), (5, 40, 5.0, 201), (6, 40, 5.0, 202)])
    leaked = build_popularity_ranking(pd.concat([train, test], ignore_index=True), CATALOGUE)
    assert leaked["movieId"].tolist() != ranking["movieId"].tolist()


def test_counts_and_averages_come_from_the_training_file_only(prepared):
    ranking, _ = load_popularity_baseline(prepared.baseline)
    train = pd.read_csv(prepared.processed / "ratings_train.csv")
    expected = train.groupby("movieId")["rating"].agg(["size", "mean"])
    actual = ranking.set_index("movieId").sort_index()
    assert actual["rating_count"].tolist() == expected["size"].tolist()
    assert np.allclose(actual["average_rating"], expected["mean"], rtol=0, atol=1e-12)
    catalogue = pd.read_csv(prepared.processed / "movies_catalogue.csv")
    assert sorted(ranking["movieId"]) == sorted(catalogue["movieId"])  # no unknown movie added


# ---------------------------------------------------------------------------
# Persistence and reproducibility
# ---------------------------------------------------------------------------


def test_manifest_records_method_sources_and_output(prepared):
    manifest = prepared.manifest
    dataset = json.loads((prepared.processed / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["baseline"]["algorithm"] == ALGORITHM
    assert manifest["source"]["training_file_sha256"] == dataset["outputs"]["train"]["sha256"]
    assert manifest["source"]["test_file_used"] is False
    assert manifest["counts"]["training_ratings"] == dataset["counts"]["train_ratings"]
    assert manifest["counts"]["movies"] == dataset["counts"]["catalogue_movies"]
    assert manifest["output"]["sha256"] == sha256_of(prepared.baseline / OUTPUT_FILES["ranking"])
    assert all(manifest["validation"].values())


def test_loaded_baseline_equals_the_computed_ranking(prepared):
    train = pd.read_csv(prepared.processed / "ratings_train.csv")
    catalogue = pd.read_csv(prepared.processed / "movies_catalogue.csv")["movieId"]
    loaded, _ = load_popularity_baseline(prepared.baseline)
    pd.testing.assert_frame_equal(loaded, build_popularity_ranking(train, catalogue), check_exact=True)


def test_second_run_is_identical_except_the_generation_time(prepared, tmp_path):
    second = run_popularity_baseline(prepared.processed, tmp_path / "run2")
    assert (prepared.baseline / OUTPUT_FILES["ranking"]).read_bytes() == (
        tmp_path / "run2" / OUTPUT_FILES["ranking"]
    ).read_bytes()
    first = {key: value for key, value in prepared.manifest.items() if key != "run"}
    assert first == {key: value for key, value in second.items() if key != "run"}


def test_existing_outputs_are_not_overwritten_by_default(prepared, tmp_path):
    out = copy_of(prepared.baseline, tmp_path)
    original = (out / OUTPUT_FILES["manifest"]).read_bytes()
    with pytest.raises(FileExistsError, match="--overwrite"):
        run_popularity_baseline(prepared.processed, out)
    assert (out / OUTPUT_FILES["manifest"]).read_bytes() == original
    run_popularity_baseline(prepared.processed, out, overwrite=True)  # allowed when requested


@pytest.mark.parametrize("missing", list(OUTPUT_FILES.values()))
def test_missing_output_file_raises(prepared, tmp_path, missing):
    out = copy_of(prepared.baseline, tmp_path)
    (out / missing).unlink()
    with pytest.raises(FileNotFoundError, match=missing):
        load_popularity_baseline(out)


@pytest.mark.parametrize("content", ["{not json", '{"output": {}}'])
def test_malformed_manifest_raises(prepared, tmp_path, content):
    out = copy_of(prepared.baseline, tmp_path)
    (out / OUTPUT_FILES["manifest"]).write_text(content, encoding="utf-8")
    with pytest.raises(DataValidationError, match="malformed"):
        load_popularity_baseline(out)


def test_edited_ranking_file_is_rejected(prepared, tmp_path):
    out = copy_of(prepared.baseline, tmp_path)
    path = out / OUTPUT_FILES["ranking"]
    path.write_bytes(path.read_bytes().replace(b"\n2,", b"\n9,", 1))
    with pytest.raises(DataValidationError, match="hash"):
        load_popularity_baseline(out)


# ---------------------------------------------------------------------------
# Integration with the data-preparation outputs
# ---------------------------------------------------------------------------


def test_training_file_changed_after_preparation_is_rejected(prepared, tmp_path):
    processed = copy_of(prepared.processed, tmp_path)
    path = processed / "ratings_train.csv"
    path.write_text(path.read_text(encoding="utf-8") + "999,1,4.0,1000000001\n", encoding="utf-8")
    with pytest.raises(DataValidationError, match="SHA-256"):
        run_popularity_baseline(processed, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_catalogue_movie_with_only_test_ratings_stops_the_run(dataset_dir, tmp_path, small_config):
    # With this configuration the pipeline keeps movie 4 in the catalogue, but all of its
    # ratings fall in the test set. The baseline must refuse instead of dropping it.
    out = tmp_path / "processed"
    run_pipeline(dataset_dir, out, tmp_path / "report.json", small_config)
    with pytest.raises(DataValidationError, match="no training rating"):
        run_popularity_baseline(out, tmp_path / "baseline")


REAL_FILES_PRESENT = (DEFAULT_OUTPUT_DIR / OUTPUT_FILES["manifest"]).is_file()


@pytest.mark.skipif(not REAL_FILES_PRESENT, reason="real MovieLens baseline not generated on this machine")
def test_real_baseline_is_consistent_with_the_prepared_dataset():
    # Read-only: loads the real artefacts, never writes.
    ranking, manifest = load_popularity_baseline(DEFAULT_OUTPUT_DIR)
    dataset = json.loads((DEFAULT_PROCESSED_DIR / "dataset_manifest.json").read_text(encoding="utf-8"))
    catalogue = pd.read_csv(DEFAULT_PROCESSED_DIR / "movies_catalogue.csv")
    assert len(ranking) == dataset["counts"]["catalogue_movies"] == 5068
    assert ranking["rating_count"].sum() == dataset["counts"]["train_ratings"]
    assert sorted(ranking["movieId"]) == sorted(catalogue["movieId"])
    assert manifest["source"]["training_file_sha256"] == dataset["outputs"]["train"]["sha256"]
