"""Small synthetic MovieLens-like datasets, so the tests never need the 877 MB ratings file."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.prepare_data import PreparationConfig


def make_movies() -> pd.DataFrame:
    # 290001 checks that large original MovieLens ids are preserved.
    return pd.DataFrame(
        {
            "movieId": [1, 2, 3, 4, 5, 6, 290001],
            "title": ["Alpha (1990)", "Beta (1991)", "Gamma (1992)", "Delta (1950)",
                      "Epsilon (2001)", "Zeta (1995)", "Eta (1960)"],
            "genres": ["Comedy", "Drama", "Action|Comedy", "Film-Noir",
                       "(no genres listed)", "Drama|Romance", "Western"],
        }
    )


def make_links() -> pd.DataFrame:
    # Movie 5 has no TMDB id, as happens for a few real MovieLens movies.
    return pd.DataFrame(
        {
            "movieId": [1, 2, 3, 4, 5, 6, 290001],
            "imdbId": [114709, 113497, 113228, 114885, 113041, 113277, 999999],
            "tmdbId": [862, 8844, 15602, 31357, np.nan, 11862, 54321],
        }
    )


def make_ratings() -> pd.DataFrame:
    """Eight regular users plus one user with too few ratings.

    Movies 1, 2, 3, 6 and 290001 are rated by everyone; movie 4 (Film-Noir) by users 1-3;
    movie 5 (no genres) by users 1-2. Timestamps increase with the order of rating.
    """
    rows = []
    for user in range(1, 9):
        rated = [1, 2, 3, 6, 290001] + ([4] if user <= 3 else []) + ([5] if user <= 2 else [])
        for i, movie in enumerate(rated):
            rating = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0][(user + i) % 10]
            rows.append((user, movie, rating, 1_000_000_000 + user * 1000 + i * 10))
    rows += [(9, 1, 4.0, 1_100_000_000), (9, 2, 3.0, 1_100_000_010)]
    return pd.DataFrame(rows, columns=["userId", "movieId", "rating", "timestamp"])


def write_dataset(folder: Path, ratings: pd.DataFrame, movies: pd.DataFrame, links: pd.DataFrame) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    ratings.to_csv(folder / "ratings.csv", index=False)
    movies.to_csv(folder / "movies.csv", index=False)
    links.to_csv(folder / "links.csv", index=False)
    return folder


@pytest.fixture
def small_config() -> PreparationConfig:
    # Top 3 movies plus one movie per genre that has at least 3 ratings; users need 5 ratings.
    return PreparationConfig(
        top_n_movies=3, genre_floor_movies=1, genre_floor_min_ratings=3, min_user_ratings=5, test_fraction=0.2
    )


@pytest.fixture
def dataset_dir(tmp_path: Path) -> Path:
    return write_dataset(tmp_path / "ml-small", make_ratings(), make_movies(), make_links())


@pytest.fixture(scope="session")
def prepared_models(tmp_path_factory):
    """Phase 2 outputs + popularity baseline + CF model for 20 synthetic users, built ONCE.

    Shared read-only by the CF and evaluation tests; tests that change files copy them first.
    Each user rates 6 or 7 of the 7 movies with seeded random ratings, so every movie keeps
    training ratings after the split.
    """
    from types import SimpleNamespace

    from src.collaborative_filtering import run_cf_training
    from src.popularity_baseline import run_popularity_baseline
    from src.prepare_data import run_pipeline

    rng = np.random.default_rng(0)
    movies = make_movies()["movieId"].tolist()
    rows = []
    for user in range(1, 21):
        rated = rng.permutation(movies)[: 6 + user % 2]
        for i, movie in enumerate(rated):
            rows.append((user, int(movie), float(rng.choice(np.arange(1, 11)) / 2), 1_000_000_000 + user * 1000 + i))
    root = tmp_path_factory.mktemp("prepared_models")
    raw = write_dataset(
        root / "raw",
        pd.DataFrame(rows, columns=["userId", "movieId", "rating", "timestamp"]),
        make_movies(),
        make_links(),
    )
    config = PreparationConfig(top_n_movies=10, genre_floor_movies=0, min_user_ratings=5, test_fraction=0.2)
    processed, models = root / "processed", root / "models"
    run_pipeline(raw, processed, root / "data_quality_report.json", config, compare_candidates=False)
    run_popularity_baseline(processed, models)
    cf_manifest = run_cf_training(processed, models, n_neighbours=3)
    return SimpleNamespace(processed=processed, models=models, cf_manifest=cf_manifest)
