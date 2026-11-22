"""Business logic for the authenticated user's own account and profile.

Every function receives the User object resolved from the access token
(get_current_user), so a user can only ever read or change their own account.
"""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.movie import Movie, split_genres
from app.models.rating import Rating
from app.models.user import User
from app.schemas.user import GenreStatistics, UserStatistics
from app.services.auth_service import EmailAlreadyRegisteredError, get_user_by_email

logger = logging.getLogger(__name__)


class IncorrectPasswordError(Exception):
    """Raised when the current password given to confirm a change is wrong."""


def update_profile(db: Session, user: User, changes: dict[str, str | None]) -> User:
    """Apply the given profile changes (name, location, bio) and save them.

    `changes` holds only the fields the client actually sent (already
    validated by UserProfileUpdate), so omitted fields are left unchanged.
    """
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    # Field names only: the values are personal data and are not logged.
    logger.info("Profile updated (user_id=%s, fields=%s)", user.id, sorted(changes))
    return user


def change_email(db: Session, user: User, new_email: str, current_password: str) -> User:
    """Change the login email after checking the current password.

    `new_email` must already be normalised by the schema. Raises
    IncorrectPasswordError or EmailAlreadyRegisteredError. Existing access
    tokens stay valid: they identify the user by ID, not by email.
    """
    if not verify_password(current_password, user.password_hash):
        raise IncorrectPasswordError
    if new_email == user.email:
        return user  # Nothing to change; not an error.
    if get_user_by_email(db, new_email) is not None:
        raise EmailAlreadyRegisteredError

    user.email = new_email
    try:
        db.commit()
    except IntegrityError as exc:
        # Another account took the same email between the check and the
        # update; the unique constraint on users.email is the final guarantee.
        db.rollback()
        raise EmailAlreadyRegisteredError from exc
    logger.info("Email changed (user_id=%s)", user.id)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    """Replace the password hash after checking the current password.

    Raises IncorrectPasswordError. Tokens issued before the change remain
    valid until they expire, because the API has no token revocation
    (a known limitation since Phase 1).
    """
    if not verify_password(current_password, user.password_hash):
        raise IncorrectPasswordError
    user.password_hash = hash_password(new_password)
    db.commit()
    logger.info("Password changed (user_id=%s)", user.id)


def rating_statistics(db: Session, user_id: int) -> UserStatistics:
    """Describe the user's stored ratings overall and per genre.

    Purely descriptive (counts and means of the ratings as they are now);
    nothing is predicted and time is not considered. One query reads the
    user's rating values together with the genres of the rated movies.
    """
    rows = db.execute(
        select(Rating.rating, Movie.genres)
        .join(Movie, Movie.movie_id == Rating.movie_id)
        .where(Rating.user_id == user_id)
    ).all()

    per_genre: defaultdict[str, list[float]] = defaultdict(list)
    for value, genres in rows:
        # A movie counts once in each of its genres.
        for genre in split_genres(genres):
            per_genre[genre].append(value)

    genre_stats = [
        GenreStatistics(
            genre=genre,
            rating_count=len(values),
            average_rating=round(sum(values) / len(values), 2),
        )
        for genre, values in per_genre.items()
    ]
    # Most rated first; ties by the higher average, then alphabetically, so
    # the order is always the same for the same ratings.
    genre_stats.sort(key=lambda g: (-g.rating_count, -g.average_rating, g.genre))

    values = [value for value, _ in rows]
    return UserStatistics(
        rating_count=len(values),
        average_rating=round(sum(values) / len(values), 2) if values else None,
        genres=genre_stats,
    )
