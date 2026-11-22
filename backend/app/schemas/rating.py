from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.rating import MAX_RATING, MIN_RATING, RATING_STEP
from app.schemas.movie import MovieSummaryRead


class RatingUpsert(BaseModel):
    """Request body for creating or updating a rating.

    The movie and the user are not part of the body: the movie comes from the
    URL path and the user from the access token, so a client cannot write a
    rating on behalf of another account.
    """

    model_config = ConfigDict(extra="forbid")

    # strict=True rejects strings such as "4.5" and booleans; integers like 4
    # are still accepted. NaN and infinity are explicitly rejected.
    rating: float = Field(
        ge=MIN_RATING,
        le=MAX_RATING,
        multiple_of=RATING_STEP,
        strict=True,
        allow_inf_nan=False,
        description="MovieLens scale: 0.5 to 5.0 in steps of 0.5",
        examples=[4.5],
    )


class RatingRead(BaseModel):
    """One of the user's ratings, with the rated movie as it is shown in lists."""

    movie_id: int
    rating: float
    created_at: datetime
    rated_at: datetime
    # Title, display title, genres and poster of the rated movie, so the
    # profile's "recent ratings" need no extra request per movie.
    movie: MovieSummaryRead
