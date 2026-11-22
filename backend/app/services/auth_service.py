"""Business logic for account registration and authentication."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_dummy_password, verify_password
from app.models.user import User

logger = logging.getLogger(__name__)


class EmailAlreadyRegisteredError(Exception):
    """Raised when registering an email that already belongs to an account."""


def get_user_by_email(db: Session, email: str) -> User | None:
    # ORM queries use bound parameters, so user input is never concatenated
    # into SQL text (protection against SQL injection).
    return db.scalar(select(User).where(User.email == email))


def register_user(db: Session, email: str, password: str, name: str) -> User:
    """Create an account. `email` and `name` must already be validated and
    normalised by the schema (RegisterRequest)."""
    if get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError

    user = User(email=email, password_hash=hash_password(password), name=name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Two simultaneous registrations can both pass the check above; the
        # unique constraint on users.email is the final guarantee.
        db.rollback()
        raise EmailAlreadyRegisteredError from exc

    # Log the internal ID only; emails and passwords are not written to logs.
    logger.info("New user account created (user_id=%s)", user.id)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Return the user if the credentials are valid, otherwise None.

    Callers cannot tell whether the email or the password was wrong, so the
    API cannot be used to discover which emails are registered.
    """
    user = get_user_by_email(db, email.strip().lower())
    if user is None:
        verify_dummy_password(password)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
