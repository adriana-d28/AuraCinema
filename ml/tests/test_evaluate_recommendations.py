"""Tests for the offline evaluation (ml/src/evaluate_recommendations.py).

Kept to the minimum that protects the protocol: metric formulas, the treatment of users
without relevant items and macro-averaging, the candidate rule, the separation of the
validation from the test set, and the end-to-end comparison on the shared synthetic
``prepared_models`` fixture (conftest.py).
"""

import json
import math
import shutil

import pandas as pd
import pytest
from src.collaborative_filtering import fit_item_cf, neighbours_fingerprint
from src.evaluate_recommendations import (
    OUTPUT_FILES,
    check_lists_respect_candidates,
    macro_average,
    popularity_recommendation_lists,
    ranking_metrics,
    relevant_items,
    run_cf_validation,
    run_discovery_evaluation,
    run_offline_evaluation,
    split_for_validation,
)
from src.popularity_baseline import load_popularity_baseline
from src.prepare_data import DataValidationError


def copy_of(folder, tmp_path):
    return shutil.copytree(folder, tmp_path / folder.name)


def test_metrics_match_the_hand_calculation():
    # Relevant {2, 5, 9}; the list hits at positions 2 and 5.
    metrics = ranking_metrics([1, 2, 3, 4, 5], {2, 5, 9}, k=5)
    idcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert metrics["precision"] == pytest.approx(2 / 5)
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["ndcg"] == pytest.approx((1 / math.log2(3) + 1 / math.log2(6)) / idcg)
    # A list shorter than K keeps K as the precision denominator.
    short = ranking_metrics([2], {2, 5, 9}, k=5)
    assert (short["precision"], short["recall"]) == (pytest.approx(1 / 5), pytest.approx(1 / 3))
    with pytest.raises(ValueError, match="undefined"):
        ranking_metrics([1], set(), k=5)


def test_users_without_relevant_items_are_excluded_and_results_are_macro_averaged():
    holdout = pd.DataFrame(
        {"userId": [1, 1, 2, 3], "movieId": [10, 20, 10, 30], "rating": [4.0, 3.5, 3.0, 5.0], "timestamp": 1}
    )
    relevant, population = relevant_items(holdout)
    assert relevant == {1: {10, 20}, 3: {30}}  # user 2 has only a 3.0 rating
    assert population["excluded_users_without_relevant_items"] == 1
    results = macro_average({1: [10, 40], 2: [10], 3: [40]}, relevant, [2], n_catalogue=4)["@2"]
    assert results["users"] == 2
    assert results["precision"] == pytest.approx((1 / 2 + 0 / 2) / 2)  # mean of per-user values
    assert results["recall"] == pytest.approx((1 / 2 + 0) / 2)
    assert results["catalogue_coverage"] == pytest.approx(2 / 4)  # movies 10 and 40


def test_a_recommendation_of_an_already_rated_movie_is_detected():
    history = pd.DataFrame({"userId": [1], "movieId": [10]})
    check_lists_respect_candidates({1: [20]}, history, catalogue={10, 20})
    with pytest.raises(DataValidationError, match="already rated"):
        check_lists_respect_candidates({1: [10]}, history, catalogue={10, 20})


def test_validation_reads_only_the_training_file_and_ignores_validation_ratings(prepared_models, tmp_path):
    processed = copy_of(prepared_models.processed, tmp_path)
    (processed / "ratings_test.csv").unlink()  # validation must not need the test set
    result = run_cf_validation(processed, tmp_path / "evaluation", candidates=(1, 2))
    assert len(result["results"]) == 4  # 2 neighbour counts x 2 scoring rules
    assert result["selected_neighbours"] in (1, 2) and result["source"]["test_file_used"] is False

    # Changing the validation ratings does not change the temporary model trained on the internal subset.
    train = pd.read_csv(processed / "ratings_train.csv")
    index_map = pd.read_csv(processed / "movie_index_map.csv")
    internal, validation = split_for_validation(train)
    changed = train.merge(validation[["userId", "movieId"]], how="left", indicator=True)
    changed["rating"] = changed["rating"].where(changed.pop("_merge") == "left_only", 5.0)
    internal_changed, _ = split_for_validation(changed)
    fingerprints = {
        neighbours_fingerprint(fit_item_cf(d, index_map, 2)[0].neighbours) for d in (internal, internal_changed)
    }
    assert len(fingerprints) == 1


def test_final_evaluation_compares_both_methods_on_the_same_users(prepared_models, tmp_path):
    result = run_offline_evaluation(prepared_models.processed, prepared_models.models, tmp_path)
    evaluated = result["population"]["evaluated_users"]
    for method in ("item_based_cf", "popularity"):
        assert [result["results"][method][at]["users"] for at in ("@5", "@10", "@20")] == [evaluated] * 3
    # The popularity results are those of the Phase 4 interface applied to the same users.
    ranking, _ = load_popularity_baseline(prepared_models.models)
    train = pd.read_csv(prepared_models.processed / "ratings_train.csv")
    relevant, _ = relevant_items(pd.read_csv(prepared_models.processed / "ratings_test.csv"))
    lists = popularity_recommendation_lists(ranking, train, sorted(relevant), 20)
    assert result["results"]["popularity"] == macro_average(lists, relevant, (5, 10, 20), 7)
    assert json.loads((tmp_path / OUTPUT_FILES["evaluation"]).read_text(encoding="utf-8")) == json.loads(
        json.dumps(result)
    )


def test_final_evaluation_rejects_a_model_trained_on_other_data(prepared_models, tmp_path):
    models = copy_of(prepared_models.models, tmp_path)
    path = models / "cf_model_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["source"]["training_file_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DataValidationError, match="trained on the current"):
        run_offline_evaluation(prepared_models.processed, models, tmp_path / "out")


def test_discovery_measurement_compares_every_mode_with_plain_cf(prepared_models, tmp_path):
    result = run_discovery_evaluation(prepared_models.processed, prepared_models.models, tmp_path)
    results = result["results"]
    assert set(results) == {"item_based_cf", "safe", "balanced", "adventurous", "popularity"}
    # Plain CF is the reference: it keeps all of itself and differs from itself by 0.
    assert results["item_based_cf"]["overlap_with_cf"] == 1.0
    assert results["item_based_cf"]["ndcg_difference_vs_cf"]["mean"] == 0.0
    for method in results.values():
        assert 0.0 <= method["intra_list_diversity"] <= 1.0 and method["novelty_bits"] >= 0.0
    assert (tmp_path / OUTPUT_FILES["discovery"]).is_file()
