"""Rating endpoints. All routes act only on the authenticated user's ratings."""

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import MovieIdPath
from app.schemas.rating import RatingRead, RatingUpsert
from app.services import rating_service

router = APIRouter(prefix="/ratings", tags=["ratings"])


@router.get("", response_model=list[RatingRead], summary="List my ratings")
def list_my_ratings(current_user: CurrentUser, db: DbSession) -> list[RatingRead]:
    ratings = rating_service.list_ratings(db, current_user.id)
    return [RatingRead.model_validate(rating) for rating in ratings]


@router.put(
    "/{movie_id}",
    response_model=RatingRead,
    summary="Create or update my rating for a movie",
    responses={
        200: {"description": "Existing rating updated"},
        201: {"description": "Rating created"},
    },
)
def upsert_my_rating(
    movie_id: MovieIdPath,
    payload: RatingUpsert,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> RatingRead:
    # PUT is idempotent: sending the same rating twice leaves the same state.
    # 201 vs 200 tells the client whether a new resource was created.
    rating, created = rating_service.upsert_rating(db, current_user.id, movie_id, payload.rating)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return RatingRead.model_validate(rating)


@router.delete(
    "/{movie_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete my rating for a movie",
    responses={404: {"description": "Rating not found"}},
)
def delete_my_rating(movie_id: MovieIdPath, current_user: CurrentUser, db: DbSession) -> None:
    if not rating_service.delete_rating(db, current_user.id, movie_id):
        # Another user's rating for the same movie also yields 404, so the
        # response never reveals what other users have rated.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")
