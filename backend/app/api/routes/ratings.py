"""Rating endpoints. All routes act only on the authenticated user's ratings."""

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, get_movie_or_404
from app.models.rating import Rating
from app.schemas.common import MovieIdPath
from app.schemas.rating import RatingRead, RatingUpsert
from app.services import movie_service, rating_service

router = APIRouter(prefix="/ratings", tags=["ratings"])


def to_rating_read(rating: Rating) -> RatingRead:
    """API representation of a rating, including the rated movie for lists."""
    return RatingRead(
        movie_id=rating.movie_id,
        rating=rating.rating,
        created_at=rating.created_at,
        rated_at=rating.rated_at,
        movie=movie_service.build_movie_summary(rating.movie),
    )


@router.get("", response_model=list[RatingRead], summary="List my ratings")
def list_my_ratings(current_user: CurrentUser, db: DbSession) -> list[RatingRead]:
    """Most recently rated first. Each rating includes the movie's title,
    display title, genres and poster."""
    ratings = rating_service.list_ratings_with_movies(db, current_user.id)
    return [to_rating_read(rating) for rating in ratings]


@router.put(
    "/{movie_id}",
    response_model=RatingRead,
    summary="Create or update my rating for a movie",
    responses={
        200: {"description": "Existing rating updated"},
        201: {"description": "Rating created"},
        404: {"description": "Movie not found in the catalogue"},
    },
)
def upsert_my_rating(
    movie_id: MovieIdPath,
    payload: RatingUpsert,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
) -> RatingRead:
    # Only catalogue movies can be rated (also enforced by a foreign key).
    get_movie_or_404(db, movie_id)
    # PUT is idempotent: sending the same rating twice leaves the same state.
    # 201 vs 200 tells the client whether a new resource was created.
    rating, created = rating_service.upsert_rating(db, current_user.id, movie_id, payload.rating)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return to_rating_read(rating)


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
