"""Business logic for a user's watchlist.

As with ratings, all queries are scoped to the user ID taken from the access
token, which isolates each user's watchlist from every other user.
"""

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.movie import Movie
from app.models.watchlist import WatchlistItem


def list_watchlist(db: Session, user_id: int) -> list[WatchlistItem]:
    """The user's watchlist, newest first, with each movie and its stored
    metadata loaded in two extra queries (no query per item), so the API can
    return titles and posters."""
    statement = (
        select(WatchlistItem)
        .where(WatchlistItem.user_id == user_id)
        .options(selectinload(WatchlistItem.movie).selectinload(Movie.movie_metadata))
        .order_by(WatchlistItem.added_at.desc(), WatchlistItem.id)
    )
    return list(db.scalars(statement))


def get_watchlist_item(db: Session, user_id: int, movie_id: int) -> WatchlistItem | None:
    return db.scalar(
        select(WatchlistItem).where(
            WatchlistItem.user_id == user_id, WatchlistItem.movie_id == movie_id
        )
    )


def add_to_watchlist(db: Session, user_id: int, movie_id: int) -> tuple[WatchlistItem, bool]:
    """Add a movie to the watchlist idempotently.

    Returns the item and True if it was added now, or the existing item and
    False if the movie was already in the watchlist (no duplicate is created
    and the original added_at timestamp is preserved).
    """
    existing = get_watchlist_item(db, user_id, movie_id)
    if existing is not None:
        return existing, False

    item = WatchlistItem(user_id=user_id, movie_id=movie_id)
    db.add(item)
    try:
        db.commit()
        return item, True
    except IntegrityError:
        # A concurrent request added the same movie first.
        db.rollback()
        existing = get_watchlist_item(db, user_id, movie_id)
        if existing is None:
            raise
        return existing, False


def remove_from_watchlist(db: Session, user_id: int, movie_id: int) -> bool:
    """Remove a movie. Returns False if it was not in the user's watchlist."""
    result = db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.user_id == user_id, WatchlistItem.movie_id == movie_id
        )
    )
    db.commit()
    return result.rowcount > 0
