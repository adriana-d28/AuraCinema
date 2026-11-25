from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.movie import RecommendedMovieRead


class RecommendationSource(StrEnum):
    """Which recommender produced the list."""

    # Item-based collaborative filtering: personalised from the user's own ratings.
    COLLABORATIVE_FILTERING = "collaborative_filtering"
    # Popularity baseline: the same ranking for everyone (minus the movies the user rated).
    POPULARITY = "popularity"


class DiscoveryMode(StrEnum):
    """How adventurous personalised recommendations are (ml/src/discovery_mode.py).

    Each mode re-ranks the same collaborative filtering candidates with a different
    weight on novelty and genre diversity; none of them is random.
    """

    SAFE = "safe"
    BALANCED = "balanced"
    ADVENTUROUS = "adventurous"


class RecommendationResponse(BaseModel):
    """The authenticated user's recommendations plus how they were produced.

    `source` and `personalized` let the frontend tell personalised results
    apart from the cold-start popularity list (and show `message` for the
    latter). Items are in recommendation order: rank 1 is the best.
    `discovery_mode` is the mode that re-ranked a personalised list. It is null
    when Discovery Mode is off (plain CF order) and for the popularity list,
    which has no user preferences to explore from.

    The meaning of each item's `score` depends on `source`, and it is never a
    predicted star rating, so the frontend should rely on `rank`:
    - collaborative_filtering: a preference-ranking score (it can be negative
      and is not comparable between users);
    - popularity: the number of MovieLens training ratings the movie received.
    """

    source: RecommendationSource
    personalized: bool = Field(description="True only for collaborative filtering results")
    message: str | None = Field(
        description="Short cold-start message for popularity results; null when personalised"
    )
    discovery_mode: DiscoveryMode | None = Field(
        description="Discovery Mode applied to the list; null when off or for popularity results"
    )
    items: list[RecommendedMovieRead] = Field(
        description="Recommended movies, best first; may hold fewer items than requested"
    )
