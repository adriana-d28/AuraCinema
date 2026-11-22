import unicodedata
from typing import Annotated

from fastapi import Path
from pydantic import AfterValidator, StringConstraints

from app.models.user import BIO_MAX_LENGTH, LOCATION_MAX_LENGTH, NAME_MAX_LENGTH

# Upper bound of PostgreSQL's INTEGER type. Larger values would fail inside the
# database, so they are rejected as validation errors (422) beforehand.
POSTGRES_INT_MAX = 2_147_483_647

MovieIdPath = Annotated[
    int,
    Path(gt=0, le=POSTGRES_INT_MAX, description="MovieLens movieId (positive integer)"),
]


# --- Profile text (name, location, bio) -------------------------------------
#
# The values are plain text typed by the user. They are trimmed, limited in
# length, and may not contain control characters (invisible characters such
# as NUL or escape sequences that could corrupt logs or the layout). A bio may
# contain line breaks, because it is typed in a multi-line field. The frontend
# renders the values as text, so HTML in them is shown literally, not executed.


def _reject_control_characters(value: str, allow_line_breaks: bool = False) -> str:
    if allow_line_breaks:
        value = value.replace("\r\n", "\n")
    for character in value:
        if allow_line_breaks and character == "\n":
            continue
        # Unicode category "Cc" = control characters (e.g. \x00, \t, \x1b).
        if unicodedata.category(character) == "Cc":
            raise ValueError("Control characters are not allowed")
    return value


def _single_line(value: str) -> str:
    return _reject_control_characters(value)


def _multi_line(value: str) -> str:
    return _reject_control_characters(value, allow_line_breaks=True)


# strip_whitespace runs before the length checks, so "   " counts as empty.
ProfileName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX_LENGTH),
    AfterValidator(_single_line),
]
ProfileLocation = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=LOCATION_MAX_LENGTH),
    AfterValidator(_single_line),
]
ProfileBio = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=BIO_MAX_LENGTH),
    AfterValidator(_multi_line),
]
