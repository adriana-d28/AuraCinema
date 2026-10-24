"""Business logic for a user's movie ratings.

Every function takes the user ID explicitly and filters by it. Route handlers
pass the ID of the authenticated user, so one user can never read or change
another user's ratings.
"""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.rating import Rating
from app.models.utils import utc_now


def list_ratings(db: Session, user_id: int) -> list[Rating]:
    statement = (
        select(Rating).where(Rating.user_id == user_id).order_by(Rating.rated_at.desc(), Rating.id)
    )
    return list(db.scalars(statement))


def get_rating(db: Session, user_id: int, movie_id: int) -> Rating | None:
    return db.scalar(select(Rating).where(Rating.user_id == user_id, Rating.movie_id == movie_id))


def upsert_rating(db: Session, user_id: int, movie_id: int, value: float) -> tuple[Rating, bool]:
    """Create the rating, or update it if the user already rated this movie.

    Returns the rating and True if it was created, False if it was updated.
    The (user_id, movie_id) unique constraint guarantees there is never more
    than one row; this function makes updates go through that single row.
    """
    rating = get_rating(db, user_id, movie_id)
    if rating is None:
        rating = Rating(user_id=user_id, movie_id=movie_id, rating=value)
        db.add(rating)
        try:
            db.commit()
            return rating, True
        except IntegrityError:
            # A concurrent request inserted the same (user, movie) rating
            # between our SELECT and INSERT. The unique constraint rejected the
            # duplicate, so we fall back to updating the existing row.
            db.rollback()
            rating = get_rating(db, user_id, movie_id)
            if rating is None:  # The error was not a duplicate; re-raise it.
                raise

    rating.rating = value
    rating.rated_at = utc_now()
    db.commit()
    return rating, False


def delete_rating(db: Session, user_id: int, movie_id: int) -> bool:
    """Delete the rating. Returns False if the user had not rated the movie."""
    result = db.execute(
        delete(Rating).where(Rating.user_id == user_id, Rating.movie_id == movie_id)
    )
    db.commit()
    return result.rowcount > 0
