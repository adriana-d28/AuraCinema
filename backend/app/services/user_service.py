"""Business logic for the authenticated user's own account and profile.

Every function receives the User object resolved from the access token
(get_current_user), so a user can only ever read or change their own account.
"""

import logging
from collections import defaultdict
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.movie import Movie, split_genres
from app.models.rating import Rating
from app.models.user import User
from app.models.user_picture import UserPicture
from app.models.utils import utc_now
from app.schemas.user import GenreStatistics, UserStatistics
from app.services.auth_service import EmailAlreadyRegisteredError, get_user_by_email

logger = logging.getLogger(__name__)

# --- Profile picture rules ---
# Largest upload accepted (2 MB). A reverse proxy in front of the API must
# allow at least this body size (e.g. nginx client_max_body_size).
PICTURE_MAX_BYTES = 2 * 1024 * 1024
# Only these formats are decoded. SVG is never accepted: it can contain scripts.
PICTURE_FORMATS = ("JPEG", "PNG", "WEBP")
# Refuse images with more pixels than this before decoding them, so a small
# file that expands into a huge image cannot exhaust the server's memory.
PICTURE_MAX_PIXELS = 40_000_000
# Every stored picture is a square JPEG of this size (pixels per side).
PICTURE_SIZE = 512
PICTURE_CONTENT_TYPE = "image/jpeg"


class IncorrectPasswordError(Exception):
    """Raised when the current password given to confirm a change is wrong."""


class InvalidPictureError(Exception):
    """Raised when an uploaded file is not a usable JPEG, PNG or WebP image."""


class PictureTooLargeError(Exception):
    """Raised when an uploaded file is larger than PICTURE_MAX_BYTES."""


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


def _reencode_picture(data: bytes) -> bytes:
    """Turn an uploaded image into a new 512x512 JPEG, or raise InvalidPictureError.

    The upload itself is never stored. Decoding it and saving a new image:
    - proves the file really is a JPEG, PNG or WebP image (its content is
      checked, not its name or the type the browser claimed);
    - drops everything except the pixels: EXIF metadata such as the GPS
      location of a phone photo, and any data hidden in the file;
    - bounds the stored size (a few tens of kilobytes).
    """
    try:
        with Image.open(BytesIO(data), formats=PICTURE_FORMATS) as image:
            # Image.open reads only the header, so the size is known here,
            # before the pixels are decoded.
            if image.width * image.height > PICTURE_MAX_PIXELS:
                raise InvalidPictureError
            # Phone photos often store their rotation as metadata; apply it
            # now, because the metadata is not kept.
            upright = ImageOps.exif_transpose(image)
            if upright.mode in ("RGBA", "LA", "P"):
                # JPEG has no transparency: transparent areas become white.
                rgba = upright.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "white")
                flat.paste(rgba, mask=rgba.getchannel("A"))
            else:
                flat = upright.convert("RGB")
            # Centre crop to a square, then resize (the avatar is round).
            square = ImageOps.fit(flat, (PICTURE_SIZE, PICTURE_SIZE))
            output = BytesIO()
            square.save(output, format="JPEG", quality=85, optimize=True)
            return output.getvalue()
    except InvalidPictureError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        # Not an image, a format we do not accept, a truncated/corrupt file
        # or an image too large to decode safely.
        raise InvalidPictureError from exc


def set_picture(db: Session, user: User, data: bytes) -> User:
    """Replace the user's profile picture with a re-encoded copy of `data`.

    Raises PictureTooLargeError or InvalidPictureError. The caller should read
    at most PICTURE_MAX_BYTES + 1 bytes, which is enough to detect a file
    that is too large without reading all of it.
    """
    if len(data) > PICTURE_MAX_BYTES:
        raise PictureTooLargeError
    content = _reencode_picture(data)
    now = utc_now()
    if user.picture is None:
        user.picture = UserPicture(content=content, content_type=PICTURE_CONTENT_TYPE)
    else:
        user.picture.content = content
        user.picture.content_type = PICTURE_CONTENT_TYPE
    user.picture.updated_at = now
    user.picture_updated_at = now
    db.commit()
    logger.info("Profile picture updated (user_id=%s)", user.id)
    return user


def get_picture(db: Session, user_id: int) -> UserPicture | None:
    """The user's stored picture, or None when they have not uploaded one."""
    return db.get(UserPicture, user_id)


def delete_picture(db: Session, user: User) -> None:
    """Remove the user's profile picture. Removing a missing picture is not an error."""
    if user.picture is not None:
        user.picture = None  # delete-orphan removes the row.
    user.picture_updated_at = None
    db.commit()
    logger.info("Profile picture removed (user_id=%s)", user.id)


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
