from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.utils import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class WatchlistItem(Base):
    """A movie (MovieLens movieId) saved by a user to watch later."""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        # A movie can appear at most once in a user's watchlist.
        UniqueConstraint("user_id", "movie_id"),
        CheckConstraint("movie_id > 0", name="movie_id_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # MovieLens movieId; must exist in the catalogue (same rule as ratings).
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.movie_id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="watchlist_items")
