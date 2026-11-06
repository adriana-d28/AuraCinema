"""Unit tests for the title/year comparison used by scripts/validate_tmdb_ids.py."""

from datetime import date

import pytest

from app.services.tmdb_service import TmdbMovieDetails
from scripts.validate_tmdb_ids import compare_titles, compare_with_tmdb


def tmdb(title: str | None, year: int | None, original_title: str | None = None):
    release = date(year, 6, 1) if year else None
    return TmdbMovieDetails(None, release, None, None, title=title, original_title=original_title)


@pytest.mark.parametrize(
    ("movielens_title", "details"),
    [
        ("Toy Story (1995)", tmdb("Toy Story", 1995)),
        ("Matrix, The (1999)", tmdb("The Matrix", 1999)),  # Trailing article.
        ("Matrix, The (1999)", tmdb("Matrix", 1999)),  # Article missing on TMDB.
        ("Léon: The Professional (a.k.a. The Professional) (Léon) (1994)",
         tmdb("Léon: The Professional", 1994, "Léon")),
        ("City of Lost Children, The (Cité des enfants perdus, La) (1995)",
         tmdb("La Cité des enfants perdus", 1995)),  # Matches the alternative title.
        ("Shanghai Triad (Yao a yao yao dao waipo qiao) (1995)",
         tmdb("Shanghai Triad", 1995, "摇啊摇，摇到外婆桥")),
        ("Lock, Stock & Two Smoking Barrels (1998)",
         tmdb("Lock, Stock and Two Smoking Barrels", 1998)),  # "&" vs "and".
        ("Father of the Bride Part II (1995)", tmdb("Father of the Bride Part 2", 1995)),
        ("Heat (1995)", tmdb("Heat", 1996)),  # One year apart is accepted.
        ("Toy Story (1995)", tmdb(None, 1995, "Toy Story")),  # Only original_title.
    ],
)  # fmt: skip
def test_valid_matches(movielens_title, details):
    assert compare_with_tmdb(movielens_title, details).status == "valid"


def test_valid_when_a_year_is_missing_says_so_in_the_note():
    outcome = compare_with_tmdb("Toy Story (1995)", tmdb("Toy Story", None))
    assert outcome.status == "valid"
    assert "year not compared" in outcome.note
    assert compare_with_tmdb("Toy Story", tmdb("Toy Story", 1995)).status == "valid"


def test_same_title_but_distant_year_is_a_year_mismatch():
    outcome = compare_with_tmdb("Heat (1995)", tmdb("Heat", 1986))
    assert outcome.status == "year_mismatch"
    assert "MovieLens 1995, TMDB 1986" in outcome.note


@pytest.mark.parametrize(
    "details", [tmdb("Avatar", 2009), tmdb("Jumanji", 1995), tmdb("Avatar", None)]
)
def test_different_title_is_a_title_mismatch_even_with_the_same_year(details):
    outcome = compare_with_tmdb("Heat (1995)", details)
    assert outcome.status == "title_mismatch"
    assert "TMDB '" in outcome.note  # The TMDB title is recorded for manual review.


def test_partial_title_with_matching_year_is_ambiguous():
    outcome = compare_with_tmdb(
        "Star Wars: Episode IV - A New Hope (1977)", tmdb("Star Wars", 1977)
    )
    assert outcome.status == "ambiguous"
    assert "manual review" in outcome.note


def test_partial_title_with_different_year_is_a_title_mismatch():
    outcome = compare_with_tmdb(
        "Star Wars: Episode IV - A New Hope (1977)", tmdb("Star Wars", 1999)
    )
    assert outcome.status == "title_mismatch"


def test_missing_tmdb_title_is_ambiguous():
    assert compare_with_tmdb("Heat (1995)", tmdb(None, 1995)).status == "ambiguous"


def test_weak_similarity_is_never_accepted():
    # "Toy Story 2" vs "Toy Story" is similar but the year (1999 vs 1995) differs.
    assert compare_with_tmdb("Toy Story 2 (1999)", tmdb("Toy Story", 1995)).status != "valid"


def test_compare_titles_reports_containment_by_whole_words():
    assert compare_titles(["Star Wars: A New Hope"], ["Star Wars"])[1] is True
    assert compare_titles(["Edit"], ["It"])[1] is False  # Too short / not a whole word.
    assert compare_titles(["Toy Story"], ["toy story"]) == (1.0, True)
