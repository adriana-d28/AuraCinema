from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.utils import utc_now

if TYPE_CHECKING:  # Imported for type hints only, avoiding circular imports.
    from app.models.rating import Rating
    from app.models.watchlist import WatchlistItem

# RFC 5321 limits an email address path to 254 characters.
EMAIL_MAX_LENGTH = 254
# Profile field lengths agreed for the Profile/Settings pages (intermediate
# backend phase). They bound storage and keep the profile layout readable.
NAME_MAX_LENGTH = 100
LOCATION_MAX_LENGTH = 100
BIO_MAX_LENGTH = 500


class User(Base):
    """An AuraCinema application account.

    These accounts are unrelated to MovieLens dataset users: MovieLens user IDs
    exist only inside the ML training data and never appear in this table.
    """

    __tablename__ = "users"
    __table_args__ = (
        # Defence in depth: the API normalises emails to lower case, and the
        # database refuses anything else, so "A@x.com" and "a@x.com" can never
        # become two separate accounts.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(EMAIL_MAX_LENGTH), unique=True, nullable=False)
    # Only the Argon2 hash is stored; the plaintext password is never persisted.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    # --- Profile (shown only to the account owner) ---
    # Data minimisation: Phase 1 stored only what authentication needs. These
    # fields were added deliberately for the Profile and Settings pages. They
    # are visible only to the owner and are deleted together with the account.
    # `name` is required by the API at registration, but stays nullable here
    # because accounts created before the field existed have no name.
    name: Mapped[str | None] = mapped_column(String(NAME_MAX_LENGTH), nullable=True)
    location: Mapped[str | None] = mapped_column(String(LOCATION_MAX_LENGTH), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(BIO_MAX_LENGTH), nullable=True)

    # passive_deletes=True lets PostgreSQL's ON DELETE CASCADE remove child rows
    # instead of SQLAlchemy loading and deleting them one by one.
    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    watchlist_items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        # Deliberately excludes the password hash.
        return f"User(id={self.id!r}, email={self.email!r})"
