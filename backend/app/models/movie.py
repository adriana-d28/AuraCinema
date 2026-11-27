from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.titles import build_search_title
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.movie_metadata import MovieMetadata

# Longest catalogue title is 114 characters and the longest genre string is 77,
# so 255 leaves comfortable room while still rejecting absurd values.
TITLE_MAX_LENGTH = 255
GENRES_MAX_LENGTH = 255

# MovieLens' own marker for a movie without genre information.
NO_GENRES_LISTED = "(no genres listed)"


def split_genres(genres: str) -> list[str]:
    """Turn the stored MovieLens genre string into a list.

    "Action|Sci-Fi|Thriller" -> ["Action", "Sci-Fi", "Thriller"]; the
    "(no genres listed)" marker becomes an empty list. Used by Movie.genre_list()
    and by queries that read only the genres column.
    """
    if genres == NO_GENRES_LISTED:
        return []
    return [genre for genre in genres.split("|") if genre]


class Movie(Base):
    """One movie of the AuraCinema catalogue (the prepared MovieLens subset).

    The primary key is the original MovieLens movieId, not a new number. The
    ratings and watchlist tables already store this ID, and the recommendation
    model will be trained on MovieLens data indexed by the same ID, so using it
    everywhere avoids any translation between identifiers.

    Title and genres are the original MovieLens values. TMDB and IMDb IDs are
    external identifiers used only to look up extra information; they are
    nullable because not every MovieLens movie has them. The MovieLens
    average rating and rating count are display information only.
    """

    __tablename__ = "movies"
    __table_args__ = (
        CheckConstraint("movie_id > 0", name="movie_id_positive"),
        CheckConstraint("tmdb_id > 0", name="tmdb_id_positive"),
        CheckConstraint("imdb_id > 0", name="imdb_id_positive"),
        CheckConstraint(
            "movielens_average_rating BETWEEN 0.5 AND 5.0",
            name="movielens_average_rating_in_scale",
        ),
        CheckConstraint("movielens_rating_count > 0", name="movielens_rating_count_positive"),
        CheckConstraint(
            "(movielens_average_rating IS NULL) = (movielens_rating_count IS NULL)",
            name="movielens_rating_statistics_together",
        ),
    )

    # autoincrement=False: the value always comes from MovieLens, never from a
    # database sequence.
    movie_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH), nullable=False)
    # Kept in the MovieLens pipe-separated format, e.g. "Action|Sci-Fi|Thriller".
    genres: Mapped[str] = mapped_column(String(GENRES_MAX_LENGTH), nullable=False)
    # Not unique: in the full MovieLens links.csv a few TMDB IDs are shared by
    # two MovieLens movies, so uniqueness would reject valid source data.
    tmdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Numeric part of the IMDb ID, as in MovieLens (114709 means "tt0114709").
    imdb_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Normalized copy of the title used only for searching (lower case, no
    # accents or punctuation, trailing articles moved back), e.g.
    # "matrix the 1999|the matrix". It is derived from `title` automatically
    # (see _sync_search_title) and never shown to users.
    search_title: Mapped[str] = mapped_column(Text, nullable=False)
    # MovieLens community rating: mean rating and number of ratings of the
    # movie in the MovieLens training ratings, imported by scripts/seed_movies.py
    # from the popularity baseline output. Not affected by AuraCinema users'
    # ratings. NULL (both together) until the seed script has stored them.
    movielens_average_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    movielens_rating_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Supplementary TMDB metadata, stored locally (one row per movie at most).
    movie_metadata: Mapped["MovieMetadata | None"] = relationship(
        back_populates="movie", uselist=False, passive_deletes=True
    )

    @validates("title")
    def _sync_search_title(self, _key: str, title: str | None) -> str | None:
        # Every time the title is set through the ORM, the search form follows.
        # A missing title is left for the database NOT NULL constraint to reject.
        self.search_title = build_search_title(title) if title is not None else None
        return title

    def genre_list(self) -> list[str]:
        """Genres as a list; the "(no genres listed)" marker becomes an empty list."""
        return split_genres(self.genres)

    def __repr__(self) -> str:
        return f"Movie(movie_id={self.movie_id!r}, title={self.title!r})"
