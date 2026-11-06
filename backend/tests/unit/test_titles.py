"""Unit tests for title normalization and MovieLens title parsing (no database)."""

import pytest

from app.core.titles import (
    SEARCH_FORM_SEPARATOR,
    ParsedTitle,
    build_search_title,
    move_trailing_article,
    normalize_text,
    parse_movielens_title,
)

# --- normalize_text ------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Toy Story", "toy story"),
        ("TOY STORY", "toy story"),
        ("  toy    story  ", "toy story"),  # Surrounding and repeated spaces.
        ("Léon", "leon"),  # Accents removed.
        ("Destin d'Amélie, Le", "destin damelie le"),
        ("Spider-Man", "spider man"),  # Hyphen separates words.
        ("Schindler's List", "schindlers list"),  # Apostrophe removed without a space.
        ("Schindler’s List", "schindlers list"),  # Typographic apostrophe too.
        ("Lock, Stock & Two Smoking Barrels", "lock stock and two smoking barrels"),
        ("WALL·E", "wall e"),
        ("Søren Kierkegaard", "soren kierkegaard"),  # Letters NFKD cannot decompose.
        ("Straße", "strasse"),  # casefold.
        ("Se7en", "se7en"),
        ("%_\\", ""),  # Only punctuation: nothing left.
        ("", ""),
    ],
)  # fmt: skip
def test_normalize_text(text, expected):
    assert normalize_text(text) == expected


def test_normalized_text_has_only_letters_digits_and_single_spaces():
    result = normalize_text("  ¡Qué! —  «Película»  #1 (2001) ")
    assert result == "que pelicula 1 2001"


# --- move_trailing_article ---------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Matrix, The", "The Matrix"),
        ("Lord of the Rings: The Two Towers, The", "The Lord of the Rings: The Two Towers"),
        ("Cité des enfants perdus, La", "La Cité des enfants perdus"),
        ("Atalante, L'", "L'Atalante"),  # No space after an elided article.
        ("Few Good Men, A", "A Few Good Men"),
        ("Toy Story", "Toy Story"),  # Nothing to move.
        ("Lock, Stock & Two", "Lock, Stock & Two"),  # "Stock" is not an article.
    ],
)  # fmt: skip
def test_move_trailing_article(title, expected):
    assert move_trailing_article(title) == expected


# --- parse_movielens_title ---------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Toy Story (1995)", ParsedTitle("Toy Story", (), 1995)),
        ("Matrix, The (1999)", ParsedTitle("The Matrix", (), 1999)),
        (
            "City of Lost Children, The (Cité des enfants perdus, La) (1995)",
            ParsedTitle("The City of Lost Children", ("La Cité des enfants perdus",), 1995),
        ),
        (
            "Léon: The Professional (a.k.a. The Professional) (Léon) (1994)",
            ParsedTitle("Léon: The Professional", ("The Professional", "Léon"), 1994),
        ),
        ("Shanghai Triad (Yao a yao yao dao waipo qiao) (1995)",
         ParsedTitle("Shanghai Triad", ("Yao a yao yao dao waipo qiao",), 1995)),
        ("(500) Days of Summer (2009)", ParsedTitle("(500) Days of Summer", (), 2009)),
        ("Some Series (2006-2007)", ParsedTitle("Some Series", (), 2006)),
        ("No Year Movie", ParsedTitle("No Year Movie", (), None)),
        ("(2019)", ParsedTitle("(2019)", (), None)),  # Only a number: kept as the title.
    ],
)  # fmt: skip
def test_parse_movielens_title(title, expected):
    assert parse_movielens_title(title) == expected


def test_all_titles_lists_main_title_first():
    parsed = parse_movielens_title(
        "City of Lost Children, The (Cité des enfants perdus, La) (1995)"
    )
    assert parsed.all_titles == ("The City of Lost Children", "La Cité des enfants perdus")


# --- build_search_title ------------------------------------------------------


def test_search_title_contains_original_and_readable_forms():
    assert build_search_title("Matrix, The (1999)") == "matrix the 1999|the matrix"


def test_search_title_for_simple_title_has_no_duplicate_forms():
    assert build_search_title("Toy Story (1995)") == "toy story 1995|toy story"


@pytest.mark.parametrize(
    ("title", "query"),
    [
        ("Matrix, The (1999)", "matrix"),
        ("Matrix, The (1999)", "the matrix"),
        ("Matrix, The (1999)", "Matrix, The"),
        ("Léon: The Professional (a.k.a. The Professional) (Léon) (1994)", "leon"),
        ("Léon: The Professional (a.k.a. The Professional) (Léon) (1994)", "LÉON the professional"),
        ("Toy Story (1995)", "TOY STORY"),
        ("Toy Story (1995)", "  toy   story "),
        ("Lock, Stock & Two Smoking Barrels (1998)", "lock stock and two"),
        ("Lock, Stock & Two Smoking Barrels (1998)", "lock, stock & two"),
        ("City of Lost Children, The (Cité des enfants perdus, La) (1995)", "la cite des enfants"),
        ("City of Lost Children, The (Cité des enfants perdus, La) (1995)", "the city of lost"),
    ],
)  # fmt: skip
def test_normalized_query_is_found_in_search_title(title, query):
    assert normalize_text(query) in build_search_title(title)


def test_query_cannot_match_across_two_forms():
    # "1999|the" would be needed to match "1999 the"; the separator prevents it.
    search_title = build_search_title("Matrix, The (1999)")
    assert SEARCH_FORM_SEPARATOR not in normalize_text("1999 | the")
    assert normalize_text("1999 the") not in search_title
