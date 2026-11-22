from datetime import datetime

from pydantic import BaseModel

from app.schemas.movie import MovieSummaryRead


class WatchlistItemRead(BaseModel):
    """One movie of the user's watchlist, with the movie as it is shown in lists."""

    movie_id: int
    added_at: datetime
    # Title, display title, genres and poster, so the Watchlist page needs no
    # extra request per movie.
    movie: MovieSummaryRead
