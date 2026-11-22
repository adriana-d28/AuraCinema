"""Watchlist endpoints. All routes act only on the authenticated user's watchlist."""

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, get_movie_or_404
from app.models.watchlist import WatchlistItem
from app.schemas.common import MovieIdPath
from app.schemas.watchlist import WatchlistItemRead
from app.services import movie_service, watchlist_service

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def to_watchlist_read(item: WatchlistItem) -> WatchlistItemRead:
    """API representation of a watchlist entry, including the movie for lists."""
    return WatchlistItemRead(
        movie_id=item.movie_id,
        added_at=item.added_at,
        movie=movie_service.build_movie_summary(item.movie),
    )


@router.get("", response_model=list[WatchlistItemRead], summary="List my watchlist")
def list_my_watchlist(current_user: CurrentUser, db: DbSession) -> list[WatchlistItemRead]:
    """Newest first. Each entry includes the movie's title, display title,
    genres and poster."""
    items = watchlist_service.list_watchlist(db, current_user.id)
    return [to_watchlist_read(item) for item in items]


@router.put(
    "/{movie_id}",
    response_model=WatchlistItemRead,
    summary="Add a movie to my watchlist",
    responses={
        200: {"description": "Movie was already in the watchlist (unchanged)"},
        201: {"description": "Movie added"},
        404: {"description": "Movie not found in the catalogue"},
    },
)
def add_to_my_watchlist(
    movie_id: MovieIdPath, current_user: CurrentUser, db: DbSession, response: Response
) -> WatchlistItemRead:
    # Only catalogue movies can be added (also enforced by a foreign key).
    get_movie_or_404(db, movie_id)
    # Idempotent: adding a movie twice is not an error and never duplicates it.
    item, created = watchlist_service.add_to_watchlist(db, current_user.id, movie_id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return to_watchlist_read(item)


@router.delete(
    "/{movie_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a movie from my watchlist",
    responses={404: {"description": "Movie not in watchlist"}},
)
def remove_from_my_watchlist(
    movie_id: MovieIdPath, current_user: CurrentUser, db: DbSession
) -> None:
    if not watchlist_service.remove_from_watchlist(db, current_user.id, movie_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Movie not in watchlist")
