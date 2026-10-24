from typing import Annotated

from fastapi import Path

# Upper bound of PostgreSQL's INTEGER type. Larger values would fail inside the
# database, so they are rejected as validation errors (422) beforehand.
POSTGRES_INT_MAX = 2_147_483_647

MovieIdPath = Annotated[
    int,
    Path(gt=0, le=POSTGRES_INT_MAX, description="MovieLens movieId (positive integer)"),
]
