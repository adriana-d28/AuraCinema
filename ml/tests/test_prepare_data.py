"""Tests for the MovieLens data-preparation pipeline (ml/src/prepare_data.py)."""

import json

import pandas as pd
import pytest

from conftest import make_links, make_movies, make_ratings, write_dataset
from src.prepare_data import (
    DataValidationError,
    PreparationConfig,
    apply_evaluation_eligibility,
    build_movie_index_map,
    clean_ratings,
    compute_training_movie_stats,
    load_source_data,
    prepare_movie_catalogue,
    run_pipeline,
    select_dataset_subset,
    split_ratings_by_user,
    validate_prepared_data,
    validate_source_data,
    verify_checksums,
)

MOVIE_IDS = make_movies()["movieId"]


def ratings_frame(rows):
    return pd.DataFrame(rows, columns=["userId", "movieId", "rating", "timestamp"])


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_missing_required_file_raises_clear_error(self, dataset_dir):
        (dataset_dir / "links.csv").unlink()
        with pytest.raises(FileNotFoundError, match="links.csv"):
            load_source_data(dataset_dir)

    def test_missing_required_column_raises(self, tmp_path):
        folder = write_dataset(tmp_path, make_ratings().drop(columns="timestamp"), make_movies(), make_links())
        with pytest.raises(DataValidationError, match="timestamp"):
            validate_source_data(load_source_data(folder))

    def test_non_numeric_column_raises(self, tmp_path):
        ratings = make_ratings().astype({"rating": str})
        ratings.loc[0, "rating"] = "five stars"
        folder = write_dataset(tmp_path, ratings, make_movies(), make_links())
        with pytest.raises(DataValidationError, match="rating"):
            validate_source_data(load_source_data(folder))

    def test_duplicate_movie_id_in_movies_file_raises(self, tmp_path):
        movies = pd.concat([make_movies(), make_movies().head(1)])
        folder = write_dataset(tmp_path, make_ratings(), movies, make_links())
        with pytest.raises(DataValidationError, match="unique"):
            validate_source_data(load_source_data(folder))

    def test_checksum_mismatch_raises(self, dataset_dir):
        lines = [f"00000000000000000000000000000000  {name}" for name in ["ratings.csv", "movies.csv", "links.csv"]]
        (dataset_dir / "checksums.txt").write_text("\n".join(lines), encoding="utf-8")
        with pytest.raises(DataValidationError, match="checksum"):
            verify_checksums(dataset_dir)

    def test_missing_and_invalid_identifiers_are_excluded(self):
        rows = [(1, 1, 4.0, 100), (None, 2, 4.0, 100), (2, -3, 4.0, 100), (2.5, 2, 4.0, 100), (0, 2, 4.0, 100)]
        clean, excluded = clean_ratings(ratings_frame(rows), MOVIE_IDS)
        assert len(clean) == 1
        assert excluded["missing_values"] == 1
        assert excluded["invalid_identifier"] == 3

    def test_invalid_rating_values_are_excluded(self):
        rows = [(1, 1, 4.5, 100), (1, 2, 0.0, 100), (1, 3, 5.5, 100), (1, 4, 3.3, 100), (1, 6, -1.0, 100)]
        clean, excluded = clean_ratings(ratings_frame(rows), MOVIE_IDS)
        assert clean["rating"].tolist() == [4.5]
        assert excluded["invalid_rating"] == 4

    def test_invalid_or_missing_timestamps_are_excluded(self):
        rows = [(1, 1, 4.0, 100), (1, 2, 4.0, None), (1, 3, 4.0, -5), (1, 4, 4.0, 4_000_000_000)]
        clean, excluded = clean_ratings(ratings_frame(rows), MOVIE_IDS)
        assert len(clean) == 1
        assert excluded["missing_values"] == 1
        assert excluded["invalid_timestamp"] == 2

    def test_rating_of_unknown_movie_is_excluded(self):
        clean, excluded = clean_ratings(ratings_frame([(1, 1, 4.0, 100), (1, 777, 4.0, 100)]), MOVIE_IDS)
        assert clean["movieId"].tolist() == [1]
        assert excluded["unknown_movie"] == 1

    def test_duplicate_pair_keeps_latest_rating(self):
        rows = [(1, 1, 2.0, 300), (1, 1, 5.0, 900), (1, 1, 3.0, 500)]
        clean, excluded = clean_ratings(ratings_frame(rows), MOVIE_IDS)
        assert len(clean) == 1
        assert clean.loc[0, "rating"] == 5.0 and clean.loc[0, "timestamp"] == 900
        assert excluded["duplicate_pair_older_rating"] == 2


# ---------------------------------------------------------------------------
# Dataset selection
# ---------------------------------------------------------------------------


class TestSelection:
    def test_selection_is_deterministic(self, small_config):
        first, info_1 = select_dataset_subset(make_ratings(), make_movies(), small_config)
        second, info_2 = select_dataset_subset(make_ratings(), make_movies(), small_config)
        pd.testing.assert_frame_equal(first, second)
        assert info_1 == info_2

    def test_top_n_ties_are_broken_by_smaller_movie_id(self):
        # Movies 1, 2, 3, 6, 290001 all have 8 ratings; top 2 must be ids 1 and 2.
        config = PreparationConfig(top_n_movies=2, genre_floor_movies=0, min_user_ratings=1)
        subset, _ = select_dataset_subset(make_ratings(), make_movies(), config)
        assert sorted(subset["movieId"].unique()) == [1, 2]

    def test_min_user_ratings_threshold(self, small_config):
        subset, info = select_dataset_subset(make_ratings(), make_movies(), small_config)
        # User 9 has 2 ratings and must be removed; every kept user has >= 5 ratings.
        assert 9 not in set(subset["userId"])
        assert subset.groupby("userId").size().min() >= small_config.min_user_ratings
        assert info["stages"][-1]["users"] == 8

    def test_genre_floor_keeps_less_popular_genres(self, small_config):
        subset, info = select_dataset_subset(make_ratings(), make_movies(), small_config)
        kept = set(subset["movieId"])
        # Film-Noir movie 4 (3 ratings) is not in the top 3 but is added by the genre floor.
        assert 4 in kept
        # "(no genres listed)" is not a genre, so movie 5 gets no floor protection.
        assert 5 not in kept
        assert info["movies_added_by_genre_floor"] >= 1

    def test_original_ids_are_preserved(self):
        config = PreparationConfig(top_n_movies=10, genre_floor_movies=0, min_user_ratings=1)
        subset, _ = select_dataset_subset(make_ratings(), make_movies(), config)
        assert 290001 in set(subset["movieId"])
        assert set(subset["userId"]).issubset(set(make_ratings()["userId"]))

    def test_dataset_smaller_than_top_n_keeps_all_movies(self):
        config = PreparationConfig(top_n_movies=5000, genre_floor_movies=0, min_user_ratings=1)
        subset, info = select_dataset_subset(make_ratings(), make_movies(), config)
        assert len(subset) == len(make_ratings())
        assert info["selected_movies"] == make_ratings()["movieId"].nunique()


# ---------------------------------------------------------------------------
# Training / test split
# ---------------------------------------------------------------------------


class TestSplit:
    def split(self, ratings=None, fraction=0.2, min_ratings=5):
        return split_ratings_by_user(make_ratings() if ratings is None else ratings, fraction, min_ratings)

    def test_train_and_test_do_not_overlap(self):
        train, test, _ = self.split()
        overlap = train.merge(test, on=["userId", "movieId"])
        assert overlap.empty
        assert len(train) + len(test) == len(make_ratings()) - 2  # user 9 is excluded

    def test_test_ratings_are_the_latest_for_each_user(self):
        train, test, _ = self.split()
        last_train = train.groupby("userId")["timestamp"].max()
        first_test = test.groupby("userId")["timestamp"].min()
        assert (last_train < first_test.loc[last_train.index]).all()

    def test_number_of_test_ratings_per_user(self):
        train, test, _ = self.split()
        # Users 1-2 have 7 ratings -> floor(1.4) = 1 test rating; users 4-8 have 5 -> 1.
        assert test.groupby("userId").size().eq(1).all()
        train_10, test_10, _ = self.split(ratings_frame([(1, m, 4.0, m) for m in range(1, 11)]), 0.2, 5)
        assert len(test_10) == 2 and test_10["movieId"].tolist() == [9, 10]

    def test_timestamp_ties_are_broken_by_movie_id(self):
        # Five ratings in the same second: the largest movieId counts as the latest.
        rows = [(1, m, 4.0, 500) for m in [40, 10, 50, 30, 20]]
        train, test, stats = self.split(ratings_frame(rows), 0.2, 5)
        assert test["movieId"].tolist() == [50]
        assert stats["users_with_boundary_timestamp_tie"] == 1
        # Shuffling the input rows must not change the result.
        shuffled = ratings_frame(rows).sample(frac=1, random_state=3)
        _, test_shuffled, _ = self.split(shuffled, 0.2, 5)
        pd.testing.assert_frame_equal(test, test_shuffled)

    def test_users_with_insufficient_history_are_excluded(self):
        train, test, stats = self.split()
        assert 9 not in set(train["userId"]) and 9 not in set(test["userId"])
        assert stats["excluded_users_insufficient_history"] == 1

    def test_ratings_remain_valid_in_both_outputs(self):
        train, test, _ = self.split()
        valid = {0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0}
        assert set(train["rating"]).issubset(valid) and set(test["rating"]).issubset(valid)

    def test_training_statistics_use_training_ratings_only(self):
        train, test, _ = self.split()
        stats = compute_training_movie_stats(train).set_index("movieId")
        assert stats["train_rating_count"].sum() == len(train)
        # Movie 290001 is every user's latest rating, so most of its ratings are in the test
        # set; its training count must not include them.
        expected = (train["movieId"] == 290001).sum()
        assert stats.loc[290001, "train_rating_count"] == expected
        assert expected < (make_ratings()["movieId"] == 290001).sum()

    def test_test_movies_unseen_in_training_are_removed_and_reported(self):
        train = ratings_frame([(1, 1, 4.0, 1), (1, 2, 4.0, 2)])
        test = ratings_frame([(1, 3, 4.0, 3), (2, 1, 5.0, 4)])
        eligible, stats = apply_evaluation_eligibility(train, test)
        assert eligible["movieId"].tolist() == [1]
        assert stats["test_ratings_removed_movie_not_in_train"] == 1
        assert stats["users_left_without_test_ratings"] == 1


# ---------------------------------------------------------------------------
# Catalogue and ID mapping
# ---------------------------------------------------------------------------


class TestCatalogueAndMapping:
    def test_catalogue_has_unique_ids_and_correct_tmdb_links(self):
        catalogue = prepare_movie_catalogue(make_movies(), make_links(), [1, 2, 290001])
        assert catalogue["movieId"].is_unique
        assert catalogue.set_index("movieId")["tmdbId"].to_dict() == {1: 862, 2: 8844, 290001: 54321}

    def test_missing_tmdb_id_keeps_the_movie(self):
        catalogue = prepare_movie_catalogue(make_movies(), make_links(), [1, 5])
        assert set(catalogue["movieId"]) == {1, 5}
        assert pd.isna(catalogue.set_index("movieId").loc[5, "tmdbId"])

    def test_movie_without_links_row_is_kept(self):
        catalogue = prepare_movie_catalogue(make_movies(), make_links()[lambda d: d["movieId"] != 2], [1, 2])
        assert set(catalogue["movieId"]) == {1, 2}
        assert pd.isna(catalogue.set_index("movieId").loc[2, "tmdbId"])

    def test_index_map_is_contiguous_and_recovers_original_ids(self):
        train = ratings_frame([(1, 290001, 4.0, 1), (1, 3, 4.0, 2), (2, 3, 4.0, 3), (2, 1, 4.0, 4)])
        index_map = build_movie_index_map(train)
        assert index_map["item_index"].tolist() == [0, 1, 2]
        assert index_map["movieId"].tolist() == [1, 3, 290001]

    def test_validation_detects_leakage_and_missing_catalogue_ids(self, small_config):
        train, raw_test, _ = split_ratings_by_user(make_ratings(), 0.2, 5)
        catalogue = prepare_movie_catalogue(make_movies(), make_links(), make_ratings()["movieId"].unique())
        index_map = build_movie_index_map(train)

        # Movie 5 is only ever a latest rating, so it exists in test but not in train.
        assert not validate_prepared_data(train, raw_test, catalogue, index_map, small_config)[
            "test_movies_in_index_map"
        ]
        test, _ = apply_evaluation_eligibility(train, raw_test)
        assert all(validate_prepared_data(train, test, catalogue, index_map, small_config).values())

        leaked_train = pd.concat([train, test.head(1)])
        checks = validate_prepared_data(leaked_train, test, catalogue, index_map, small_config)
        assert not checks["train_test_pairs_disjoint"]
        assert not checks["train_precedes_test_for_every_user"]

        checks = validate_prepared_data(train, test, catalogue[catalogue["movieId"] != 1], index_map, small_config)
        assert not checks["train_movies_in_catalogue"]


# ---------------------------------------------------------------------------
# Full pipeline and reproducibility
# ---------------------------------------------------------------------------


class TestPipeline:
    def run(self, dataset_dir, out_dir, config, overwrite=False):
        return run_pipeline(dataset_dir, out_dir, out_dir / "report.json", config, overwrite=overwrite)

    def test_two_runs_produce_identical_outputs(self, dataset_dir, tmp_path, small_config):
        first = self.run(dataset_dir, tmp_path / "run1", small_config)
        second = self.run(dataset_dir, tmp_path / "run2", small_config)
        for key in ["train", "test", "catalogue", "index_map"]:
            assert first["outputs"][key]["sha256"] == second["outputs"][key]["sha256"]
            file_1 = (tmp_path / "run1" / first["outputs"][key]["file"]).read_bytes()
            file_2 = (tmp_path / "run2" / second["outputs"][key]["file"]).read_bytes()
            assert file_1 == file_2

    def test_manifest_matches_written_files(self, dataset_dir, tmp_path, small_config):
        out = tmp_path / "out"
        self.run(dataset_dir, out, small_config)
        manifest = json.loads((out / "dataset_manifest.json").read_text(encoding="utf-8"))
        train = pd.read_csv(out / "ratings_train.csv")
        test = pd.read_csv(out / "ratings_test.csv")
        catalogue = pd.read_csv(out / "movies_catalogue.csv")

        assert manifest["parameters"]["top_n_movies"] == small_config.top_n_movies
        assert manifest["counts"]["train_ratings"] == len(train) == manifest["outputs"]["train"]["rows"]
        assert manifest["counts"]["test_ratings"] == len(test)
        assert manifest["counts"]["catalogue_movies"] == len(catalogue)
        assert manifest["counts"]["users"] == train["userId"].nunique()
        assert list(train.columns) == ["userId", "movieId", "rating", "timestamp"]
        assert list(catalogue.columns) == ["movieId", "title", "genres", "imdbId", "tmdbId"]
        assert all(manifest["validation"].values())

    def test_existing_outputs_are_not_overwritten_by_default(self, dataset_dir, tmp_path, small_config):
        out = tmp_path / "out"
        self.run(dataset_dir, out, small_config)
        with pytest.raises(FileExistsError):
            self.run(dataset_dir, out, small_config)
        self.run(dataset_dir, out, small_config, overwrite=True)  # allowed when requested
