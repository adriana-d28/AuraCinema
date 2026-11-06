"""Reusable FastAPI dependencies for database access and authentication."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db
from app.models.movie import Movie
from app.models.user import User

# Reads the "Authorization: Bearer <token>" header. tokenUrl tells Swagger UI
# where to send credentials when the "Authorize" button is used.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """Resolve the authenticated user from the bearer token.

    This is the only source of user identity for protected endpoints; user IDs
    in URLs or request bodies are never trusted. A token that is invalid,
    expired, or refers to a deleted account gets the same 401 response.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        raise credentials_error from None

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_movie_or_404(db: Session, movie_id: int) -> Movie:
    """Return the catalogue movie, or respond 404 if the ID is not in the catalogue."""
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not found")
    return movie
