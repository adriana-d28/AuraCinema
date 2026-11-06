"""Helpers for MovieLens titles: text normalization and title parsing.

MovieLens titles follow a few conventions that make naive matching fail:

- the release year is part of the title: "Toy Story (1995)";
- a leading article is moved to the end: "Matrix, The (1999)";
- alternative (often original-language) titles are added in parentheses:
  "Léon: The Professional (a.k.a. The Professional) (Léon) (1994)".

The functions here are used in two places:

1. Local search: `build_search_title` produces the value stored in
   movies.search_title, and `normalize_text` is applied to the user's query,
   so both sides are compared in the same normalized form.
2. TMDB ID validation: `parse_movielens_title` extracts the main title, the
   alternative titles and the year, to compare them with TMDB's answer.

Only the Python standard library is used (unicodedata, re).
"""

import re
import unicodedata
from dataclasses import dataclass

# Letters that Unicode decomposition (NFKD) does not reduce to a plain letter.
_SPECIAL_LETTERS = str.maketrans(
    {"ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i"}
)
# Apostrophes are removed without a space, so "Schindler's" matches "schindlers".
_APOSTROPHES = str.maketrans("", "", "'’‘`´")
# Anything that is not a letter or a digit separates words.
_NON_WORD = re.compile(r"[\W_]+")

# Articles that MovieLens moves to the end of a title ("Matrix, The").
# English plus the most common articles of the other languages in the catalogue.
TRAILING_ARTICLES = (
    "The", "A", "An",  # English
    "Les", "La", "Le", "L'", "Un", "Une",  # French
    "El", "Los", "Las",  # Spanish
    "Il", "Lo", "Gli", "I",  # Italian
    "Das", "Der", "Die", "Ein", "Eine",  # German
    "O", "Os", "As",  # Portuguese
    "De", "Het", "Een",  # Dutch
    "Den", "Det", "En", "Ett",  # Scandinavian
)  # fmt: skip
_TRAILING_ARTICLE = re.compile(
    r"^(?P<rest>.+), (?P<article>" + "|".join(re.escape(a) for a in TRAILING_ARTICLES) + r")$",
    re.IGNORECASE,
)
# "(1995)" at the end of a MovieLens title; a few entries use a range "(2006-2007)".
_YEAR = re.compile(r"^(?P<rest>.*?)\s*\((?P<year>\d{4})(?:[-–]\d{0,4})?\)\s*$")
# One parenthesised group at the end: "Shanghai Triad (Yao a yao yao dao waipo qiao)".
_TRAILING_GROUP = re.compile(r"^(?P<rest>.*\S)\s*\((?P<group>[^()]*)\)$")
_AKA = re.compile(r"^a\.?k\.?a\.?\s+", re.IGNORECASE)

# Separator between the alternative forms stored in search_title. Normalized
# text never contains it, so a query can never match across two forms.
SEARCH_FORM_SEPARATOR = "|"


def normalize_text(text: str) -> str:
    """Return a lower-case, accent-free, punctuation-free form of `text`.

    >>> normalize_text("  Léon: The Professional ")
    'leon the professional'
    >>> normalize_text("Lock, Stock & Two Smoking Barrels")
    'lock stock and two smoking barrels'
    """
    # NFKD splits "é" into "e" + a combining accent, which is then dropped.
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = without_accents.casefold().translate(_SPECIAL_LETTERS).translate(_APOSTROPHES)
    folded = folded.replace("&", " and ")
    return " ".join(_NON_WORD.sub(" ", folded).split())


def move_trailing_article(title: str) -> str:
    """Turn "Matrix, The" into "The Matrix" (and "Atalante, L'" into "L'Atalante")."""
    match = _TRAILING_ARTICLE.match(title.strip())
    if match is None:
        return title.strip()
    article = match.group("article")
    separator = "" if article.endswith("'") else " "
    return f"{article}{separator}{match.group('rest')}"


@dataclass(frozen=True)
class ParsedTitle:
    """A MovieLens title split into its parts, with trailing articles moved back."""

    main: str
    alternatives: tuple[str, ...]
    year: int | None

    @property
    def all_titles(self) -> tuple[str, ...]:
        return (self.main, *self.alternatives)


def parse_movielens_title(title: str) -> ParsedTitle:
    """Split a MovieLens title into main title, alternative titles and year.

    >>> parse_movielens_title("City of Lost Children, The (Cité des enfants perdus, La) (1995)")
    ParsedTitle(main='The City of Lost Children', alternatives=('La Cité des enfants perdus',), \
year=1995)
    """
    rest = title.strip()
    year = None
    year_match = _YEAR.match(rest)
    if year_match is not None and year_match.group("rest"):
        rest, year = year_match.group("rest"), int(year_match.group("year"))

    alternatives: list[str] = []
    while (group_match := _TRAILING_GROUP.match(rest)) is not None:
        alternative = _AKA.sub("", group_match.group("group").strip())
        if alternative:
            alternatives.insert(0, move_trailing_article(alternative))
        rest = group_match.group("rest")

    return ParsedTitle(
        main=move_trailing_article(rest), alternatives=tuple(alternatives), year=year
    )


def build_search_title(title: str) -> str:
    """Build the normalized value stored in movies.search_title.

    It contains the normalized original title plus the readable forms of the
    main and alternative titles, separated by SEARCH_FORM_SEPARATOR, e.g.

        "Matrix, The (1999)" -> "matrix the 1999|the matrix"

    so that both "matrix the" and "the matrix" find the movie. The original
    MovieLens title itself is never modified.
    """
    parsed = parse_movielens_title(title)
    forms: list[str] = []
    for text in (title, *parsed.all_titles):
        normalized = normalize_text(text)
        if normalized and normalized not in forms:
            forms.append(normalized)
    return SEARCH_FORM_SEPARATOR.join(forms)
