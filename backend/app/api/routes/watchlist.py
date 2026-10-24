"""Watchlist endpoints. All routes act only on the authenticated user's watchlist."""

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import MovieIdPath
from app.schemas.watchlist import WatchlistItemRead
from app.services import watchlist_service

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItemRead], summary="List my watchlist")
def list_my_watchlist(current_user: CurrentUser, db: DbSession) -> list[WatchlistItemRead]:
    items = watchlist_service.list_watchlist(db, current_user.id)
    return [WatchlistItemRead.model_validate(item) for item in items]


@router.put(
    "/{movie_id}",
    response_model=WatchlistItemRead,
    summary="Add a movie to my watchlist",
    responses={
        200: {"description": "Movie was already in the watchlist (unchanged)"},
        201: {"description": "Movie added"},
    },
)
def add_to_my_watchlist(
    movie_id: MovieIdPath, current_user: CurrentUser, db: DbSession, response: Response
) -> WatchlistItemRead:
    # Idempotent: adding a movie twice is not an error and never duplicates it.
    item, created = watchlist_service.add_to_watchlist(db, current_user.id, movie_id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return WatchlistItemRead.model_validate(item)


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
