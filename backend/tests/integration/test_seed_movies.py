"""Tests for the catalogue import script (scripts/seed_movies.py).

Small temporary CSV files are used. One test also reads the real prepared
catalogue (0.3 MB) when it exists locally; the large rating files are never needed.
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Movie, MovieMetadata, Rating, User, WatchlistItem
from scripts.seed_movies import (
    DEFAULT_CSV_PATH,
    DEFAULT_RATINGS_CSV_PATH,
    CatalogueError,
    MovieRecord,
    add_rating_statistics,
    import_movies,
    load_catalogue,
    load_rating_statistics,
    main,
)
from tests.helpers import TEST_MOVIES

HEADER = "movieId,title,genres,imdbId,tmdbId\n"
VALID_ROWS = (
    "1,Toy Story (1995),Adventure|Animation|Children|Comedy|Fantasy,114709,862\n"
    '318,"Shawshank Redemption, The (1994)",Crime|Drama,111161,278\n'
    "7842,Dune (2000),Drama|Fantasy|Sci-Fi,142032,\n"
    "288513,Test (2023),(no genres listed),,\n"
)


RATINGS_HEADER = "rank,movieId,popularity_score,rating_count,average_rating\n"
# Movie 288513 has no row, so it keeps no MovieLens rating.
RATINGS_ROWS = (
    "1,318,95088,95088,4.410340947332997\n"
    "2,1,68997,68997,3.8970172616200703\n"
    "3,7842,1103,1103,3.2\n"
)


def write_csv(tmp_path: Path, content: str, name: str = "movies_catalogue.csv") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def write_ratings_csv(tmp_path: Path, content: str = RATINGS_HEADER + RATINGS_ROWS) -> Path:
    return write_csv(tmp_path, content, "popularity_baseline.csv")


def empty_movies_table(db: Session) -> None:
    db.execute(text("DELETE FROM movies"))
    db.commit()


def count_movies(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Movie))


# --- Reading and validating the CSV (no database needed) --------------------


def test_valid_csv_is_loaded_with_original_values(tmp_path):
    records = load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS))
    assert records == [
        MovieRecord(
            1, "Toy Story (1995)", "Adventure|Animation|Children|Comedy|Fantasy", 862, 114709
        ),
        MovieRecord(318, "Shawshank Redemption, The (1994)", "Crime|Drama", 278, 111161),
        MovieRecord(7842, "Dune (2000)", "Drama|Fantasy|Sci-Fi", None, 142032),
        MovieRecord(288513, "Test (2023)", "(no genres listed)", None, None),
    ]


def test_column_order_does_not_matter(tmp_path):
    path = write_csv(
        tmp_path, "tmdbId,movieId,genres,title,imdbId\n862,1,Comedy,Toy Story,114709\n"
    )
    assert load_catalogue(path) == [MovieRecord(1, "Toy Story", "Comedy", 862, 114709)]


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(CatalogueError, match="not found"):
        load_catalogue(tmp_path / "does_not_exist.csv")


@pytest.mark.parametrize("missing", ["movieId", "title", "genres", "imdbId", "tmdbId"])
def test_missing_required_column_is_reported(tmp_path, missing):
    columns = [c for c in ["movieId", "title", "genres", "imdbId", "tmdbId"] if c != missing]
    path = write_csv(tmp_path, ",".join(columns) + "\n")
    with pytest.raises(CatalogueError, match=f"Missing required column\\(s\\): {missing}"):
        load_catalogue(path)


@pytest.mark.parametrize("bad_id", ["", "0", "-1", "abc", "1.5", "1e3", "2147483648"])
def test_invalid_movie_id_is_reported_with_row_number(tmp_path, bad_id):
    path = write_csv(tmp_path, HEADER + f"1,A,Drama,1,1\n{bad_id},B,Drama,2,2\n")
    with pytest.raises(CatalogueError, match="Row 3: movieId"):
        load_catalogue(path)


@pytest.mark.parametrize("column", ["tmdbId", "imdbId"])
@pytest.mark.parametrize("bad_value", ["0", "-5", "862.0", "tt0114709"])
def test_invalid_external_id_is_reported(tmp_path, column, bad_value):
    values = {"tmdbId": "862", "imdbId": "114709", column: bad_value}
    path = write_csv(
        tmp_path, HEADER + f"1,Toy Story,Comedy,{values['imdbId']},{values['tmdbId']}\n"
    )
    with pytest.raises(CatalogueError, match=f"Row 2: {column}"):
        load_catalogue(path)


def test_empty_external_ids_become_none(tmp_path):
    (record,) = load_catalogue(write_csv(tmp_path, HEADER + "7842,Dune (2000),Drama,,\n"))
    assert record.tmdb_id is None
    assert record.imdb_id is None


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("1,,Drama,1,1", "title is empty"),
        ("1,Title,,1,1", "genres is empty"),
        ("1," + "x" * 256 + ",Drama,1,1", "title is longer than 255"),
        ("1,Title", "too few columns"),
    ],
)
def test_invalid_text_fields_are_reported(tmp_path, row, message):
    with pytest.raises(CatalogueError, match=message):
        load_catalogue(write_csv(tmp_path, HEADER + row + "\n"))


def test_duplicate_movie_ids_are_reported(tmp_path):
    path = write_csv(tmp_path, HEADER + "1,A,Drama,1,1\n2,B,Drama,2,2\n1,C,Drama,3,3\n")
    with pytest.raises(CatalogueError, match="Row 4: duplicate movieId 1"):
        load_catalogue(path)


def test_file_without_movies_is_rejected(tmp_path):
    with pytest.raises(CatalogueError, match="no movies"):
        load_catalogue(write_csv(tmp_path, HEADER))


def test_rating_statistics_are_added_to_the_records(tmp_path):
    records = add_rating_statistics(
        load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS)),
        load_rating_statistics(write_ratings_csv(tmp_path)),
    )
    assert {
        r.movie_id: (r.movielens_average_rating, r.movielens_rating_count) for r in records
    } == {
        1: (3.8970172616200703, 68997),
        318: (4.410340947332997, 95088),
        7842: (3.2, 1103),
        288513: (None, None),  # No row in the ratings file.
    }


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("1,318,1,1,5.5", "outside 0.5-5.0"),
        ("1,318,1,1,nan", "outside 0.5-5.0"),
        ("1,318,1,1,abc", "not a number"),
        ("1,318,0,0,4.0", "rating_count"),
        ("1,318,1,1,4.0\n2,318,1,1,4.0", "duplicate movieId 318"),
    ],
)
def test_invalid_rating_statistics_are_reported(tmp_path, row, message):
    with pytest.raises(CatalogueError, match=message):
        load_rating_statistics(write_ratings_csv(tmp_path, RATINGS_HEADER + row + "\n"))


# --- Importing into PostgreSQL --------------------------------------------------

# Tests below that use the database are marked with @pytest.mark.db.


@pytest.mark.db
def test_import_into_empty_table_inserts_all_records(db_session: Session, tmp_path):
    empty_movies_table(db_session)
    records = load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS))

    result = import_movies(db_session, records)

    assert (result.inserted, result.updated, result.skipped) == (4, 0, 0)
    assert count_movies(db_session) == 4
    dune = db_session.get(Movie, 7842)
    assert (dune.title, dune.genres, dune.tmdb_id, dune.imdb_id) == (
        "Dune (2000)",
        "Drama|Fantasy|Sci-Fi",
        None,
        142032,
    )


@pytest.mark.db
def test_repeated_import_does_not_create_duplicates(db_session: Session, tmp_path):
    empty_movies_table(db_session)
    records = load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS))
    import_movies(db_session, records)

    second = import_movies(db_session, records)

    assert (second.inserted, second.updated, second.skipped) == (0, 0, 4)
    assert count_movies(db_session) == 4


@pytest.mark.db
def test_changed_rows_are_updated(db_session: Session, tmp_path):
    empty_movies_table(db_session)
    import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS)))

    changed = VALID_ROWS.replace(
        "7842,Dune (2000),Drama|Fantasy|Sci-Fi,142032,",
        "7842,Dune (2000),Drama|Fantasy|Sci-Fi,142032,841",
    )
    result = import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + changed)))

    assert (result.inserted, result.updated, result.skipped) == (0, 1, 3)
    db_session.expire_all()
    assert db_session.get(Movie, 7842).tmdb_id == 841


@pytest.mark.db
def test_import_preserves_existing_user_data(db_session: Session, tmp_path):
    """Re-importing the catalogue keeps users, ratings and watchlist entries,
    and movies missing from the file are not deleted."""
    user = User(email="keep@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.add_all(
        [
            Rating(user_id=user.id, movie_id=318, rating=5.0),
            WatchlistItem(user_id=user.id, movie_id=2571),
        ]
    )
    db_session.commit()

    result = import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS)))

    assert result.inserted == 1  # Only 288513 is new; 1, 318 and 7842 already exist.
    assert db_session.scalar(select(func.count()).select_from(Rating)) == 1
    assert db_session.scalar(select(func.count()).select_from(WatchlistItem)) == 1
    assert db_session.get(Movie, 2571) is not None  # Not in the CSV, but not deleted.
    assert count_movies(db_session) == len(TEST_MOVIES) + 1


@pytest.mark.db
def test_failed_import_leaves_catalogue_unchanged(db_session: Session):
    """The import is one transaction: an error in the middle rolls everything back."""
    before = count_movies(db_session)
    records = [
        MovieRecord(500_001, "New movie", "Drama", None, None),
        # Bypasses CSV validation to force a database error (CHECK tmdb_id > 0).
        MovieRecord(500_002, "Broken movie", "Drama", -1, None),
    ]
    with pytest.raises(Exception, match="tmdb_id_positive"):
        import_movies(db_session, records)
    assert count_movies(db_session) == before
    assert db_session.get(Movie, 500_001) is None


@pytest.mark.db
def test_command_line_import_reports_counts(clean_db, tmp_path, capsys):
    args = ["--csv", str(write_csv(tmp_path, HEADER + VALID_ROWS))]
    args += ["--ratings-csv", str(write_ratings_csv(tmp_path))]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "MovieLens rating statistics found for 3 of them" in output
    # 1, 318 and 7842 exist without a MovieLens rating, so they are updated.
    assert "Inserted: 1  Updated: 3  Skipped (unchanged): 0" in output
    assert f"Movies now in the database: {len(TEST_MOVIES) + 1}" in output

    from app.db.session import get_session_factory

    with get_session_factory()() as db:
        movie = db.get(Movie, 318)
        assert (movie.movielens_average_rating, movie.movielens_rating_count) == (
            4.410340947332997,
            95088,
        )
        assert db.get(Movie, 288513).movielens_rating_count is None

    assert main(args) == 0  # A second run changes nothing.
    assert "Inserted: 0  Updated: 0  Skipped (unchanged): 4" in capsys.readouterr().out


def test_command_line_reports_invalid_file(tmp_path, capsys):
    assert main(["--csv", str(tmp_path / "missing.csv")]) == 1
    assert "Catalogue file not found" in capsys.readouterr().err


# --- Interaction with movie_metadata and search_title -------------------------


@pytest.mark.db
def test_import_computes_the_normalized_search_title(db_session: Session, tmp_path):
    empty_movies_table(db_session)
    import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS)))
    db_session.expire_all()
    assert db_session.get(Movie, 318).search_title == (
        "shawshank redemption the 1994|the shawshank redemption"
    )
    assert db_session.get(Movie, 318).title == "Shawshank Redemption, The (1994)"  # Unchanged.


@pytest.mark.db
def test_outdated_search_title_is_recomputed(db_session: Session, tmp_path):
    db_session.execute(text("UPDATE movies SET search_title = '' WHERE movie_id = 1"))
    db_session.commit()
    result = import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS)))
    assert (result.inserted, result.updated, result.skipped) == (1, 1, 2)
    db_session.expire_all()
    assert db_session.get(Movie, 1).search_title == "toy story 1995|toy story"


@pytest.mark.db
def test_changed_tmdb_id_removes_metadata_of_the_old_id(db_session: Session, tmp_path):
    db_session.add_all(
        [
            MovieMetadata(movie_id=1, runtime=81, tmdb_validation_status="valid"),
            MovieMetadata(movie_id=318, runtime=142, tmdb_validation_status="valid"),
        ]
    )
    db_session.commit()
    changed = VALID_ROWS.replace("114709,862", "114709,999")  # New TMDB ID for movie 1.

    result = import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + changed)))

    assert result.metadata_reset == 1
    db_session.expire_all()
    assert db_session.get(MovieMetadata, 1) is None  # Belonged to TMDB ID 862.
    assert db_session.get(MovieMetadata, 318).runtime == 142  # Unaffected.


@pytest.mark.db
def test_other_changes_keep_stored_metadata(db_session: Session, tmp_path):
    db_session.add(MovieMetadata(movie_id=1, runtime=81))
    db_session.commit()
    changed = VALID_ROWS.replace("Toy Story (1995)", "Toy Story! (1995)")
    result = import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + changed)))
    assert (result.updated, result.metadata_reset) == (1, 0)
    db_session.expire_all()
    assert db_session.get(MovieMetadata, 1).runtime == 81


@pytest.mark.db
def test_import_never_contacts_tmdb(db_session: Session, tmp_path, monkeypatch):
    from app.services import tmdb_service

    def forbidden(*args, **kwargs):
        raise AssertionError("the catalogue import must not call TMDB")

    monkeypatch.setattr(tmdb_service.TmdbClient, "__init__", forbidden)
    empty_movies_table(db_session)
    result = import_movies(db_session, load_catalogue(write_csv(tmp_path, HEADER + VALID_ROWS)))
    assert result.inserted == 4
    assert db_session.scalar(select(func.count()).select_from(MovieMetadata)) == 0


@pytest.mark.db
def test_command_line_reports_metadata_reset(clean_db, tmp_path, capsys):
    from app.db.session import get_session_factory

    with get_session_factory()() as db:
        db.add(MovieMetadata(movie_id=1, runtime=81))
        db.commit()
    changed = VALID_ROWS.replace("114709,862", "114709,999")
    assert main(["--csv", str(write_csv(tmp_path, HEADER + changed))]) == 0
    assert "Stored TMDB metadata removed because the TMDB ID changed: 1" in capsys.readouterr().out


# --- The real prepared catalogue ------------------------------------------------

real_catalogue_required = pytest.mark.skipif(
    not DEFAULT_CSV_PATH.is_file(),
    reason="ml/data/processed/movies_catalogue.csv not available (generated locally, not in Git)",
)


@real_catalogue_required
def test_real_catalogue_is_valid():
    records = load_catalogue(DEFAULT_CSV_PATH)
    assert len(records) == 5068
    # Every catalogue movie has a MovieLens rating in the popularity baseline.
    statistics = load_rating_statistics(DEFAULT_RATINGS_CSV_PATH)
    assert set(statistics) == {r.movie_id for r in records}
    without_tmdb = [r.movie_id for r in records if r.tmdb_id is None]
    assert without_tmdb == [7842]


@real_catalogue_required
@pytest.mark.db
def test_real_catalogue_import_into_empty_table(db_session: Session):
    empty_movies_table(db_session)
    result = import_movies(db_session, load_catalogue(DEFAULT_CSV_PATH))
    assert (result.inserted, result.updated, result.skipped) == (5068, 0, 0)
    assert count_movies(db_session) == 5068
    # Every movie received a non-empty normalized search title.
    empty = db_session.scalar(
        select(func.count()).select_from(Movie).where(Movie.search_title == "")
    )
    assert empty == 0

    # The test catalogue rows are exact copies of real catalogue rows.
    for movie_id, title, genres, tmdb_id, imdb_id in TEST_MOVIES:
        movie = db_session.get(Movie, movie_id)
        assert (movie.title, movie.genres, movie.tmdb_id, movie.imdb_id) == (
            title,
            genres,
            tmdb_id,
            imdb_id,
        )
