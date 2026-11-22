from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.utils import utc_now

if TYPE_CHECKING:
    from app.models.movie import Movie
    from app.models.user import User

# MovieLens rating scale: 0.5 to 5.0 stars in half-star steps. Using the same
# scale lets application ratings be combined with the MovieLens-trained model.
MIN_RATING = 0.5
MAX_RATING = 5.0
RATING_STEP = 0.5


class Rating(Base):
    """A user's star rating for one movie (identified by its MovieLens movieId)."""

    __tablename__ = "ratings"
    __table_args__ = (
        # One rating per user per movie; re-rating updates the existing row.
        UniqueConstraint("user_id", "movie_id"),
        CheckConstraint("movie_id > 0", name="movie_id_positive"),
        # The database enforces the same range and half-star rule as the API,
        # so invalid values cannot be written even by code that bypasses it.
        CheckConstraint(
            "rating >= 0.5 AND rating <= 5.0 AND rating * 2 = floor(rating * 2)",
            name="rating_half_star_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # MovieLens movieId. The foreign key guarantees the movie exists in the
    # catalogue. Without ON DELETE, PostgreSQL refuses to delete a movie that
    # still has ratings, so user data can never be removed by accident.
    movie_id: Mapped[int] = mapped_column(Integer, ForeignKey("movies.movie_id"), nullable=False)
    # NUMERIC(2,1) stores half-star values exactly (no floating-point drift);
    # asdecimal=False returns Python floats, which serialise as JSON numbers.
    rating: Mapped[float] = mapped_column(Numeric(2, 1, asdecimal=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    # Time the current rating value was given. Like the MovieLens timestamp,
    # it changes when the user re-rates the movie; Taste Evolution will use it.
    rated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="ratings")
    # The rated catalogue movie. ORM-only: it uses the existing foreign key
    # (no schema change) and lets the API return the title and poster with
    # each rating. One-directional, so Movie objects never load their ratings.
    movie: Mapped["Movie"] = relationship()
