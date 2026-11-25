"""Recommendation endpoint. It acts only on the authenticated user's ratings.

The route stays thin: it validates the query parameter, identifies the user from
the token and delegates everything else to the recommendation service.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.recommendation import DiscoveryMode, RecommendationResponse
from app.services import recommendation_service
from app.services.recommendation_service import Recommenders

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])

DEFAULT_RECOMMENDATIONS = 10
MAX_RECOMMENDATIONS = 20


@router.get(
    "",
    response_model=RecommendationResponse,
    summary="Get my movie recommendations",
    responses={503: {"description": "The recommendation model is temporarily unavailable"}},
)
def get_my_recommendations(
    current_user: CurrentUser,
    db: DbSession,
    # The models are loaded once at start-up; this dependency returns the
    # already-loaded objects (tests replace it with fake recommenders).
    recommenders: Annotated[Recommenders, Depends(recommendation_service.load_recommenders)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_RECOMMENDATIONS,
            description=f"Number of recommendations (1-{MAX_RECOMMENDATIONS})",
        ),
    ] = DEFAULT_RECOMMENDATIONS,
    discovery_mode: Annotated[
        DiscoveryMode | None,
        Query(description="Turns Discovery Mode on; leave it out for plain recommendations"),
    ] = None,
) -> RecommendationResponse:
    """Personalised (collaborative filtering) recommendations, or popular movies
    while the user has too little rating history. There is no user ID parameter:
    the user always comes from the access token. Movies the user has rated are
    never returned; watchlist movies can be.

    Discovery Mode is optional and off by default: without `discovery_mode` the
    personalised list keeps the model's own order. With `safe`, `balanced` or
    `adventurous` it is re-ranked for more novelty and diversity. Popularity
    results are never re-ranked; the response then says null."""
    try:
        return recommendation_service.recommend_for_user(
            db, current_user.id, limit, recommenders, discovery_mode
        )
    except recommendation_service.RecommendationUnavailableError as error:
        # The loading error itself was logged in full at start-up; the client gets
        # no file paths or internal details.
        logger.error("Recommendation request failed: %s", error)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendations are temporarily unavailable",
        ) from None
