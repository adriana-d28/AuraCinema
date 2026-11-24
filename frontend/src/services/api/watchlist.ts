// Watchlist endpoints (backend/app/api/routes/watchlist.py). Login required:
// every call acts only on the signed-in user's own watchlist.
//   - GET    /watchlist             -> WatchlistItem[] (newest first)
//   - PUT    /watchlist/{movie_id}  -> WatchlistItem (201 added / 200 already there, never duplicated)
//   - DELETE /watchlist/{movie_id}  -> 204 (404 when the movie is not in the watchlist)
// The watchlist is independent from ratings: none of these calls touches a rating.

import { apiRequest } from './client'
import type { WatchlistItem } from './types'

export function listMyWatchlist(token: string, signal?: AbortSignal): Promise<WatchlistItem[]> {
  return apiRequest<WatchlistItem[]>('/watchlist', { token, signal })
}

export function addToWatchlist(token: string, movieId: number): Promise<WatchlistItem> {
  return apiRequest<WatchlistItem>(`/watchlist/${movieId}`, { method: 'PUT', token })
}

export function removeFromWatchlist(token: string, movieId: number): Promise<void> {
  return apiRequest<void>(`/watchlist/${movieId}`, { method: 'DELETE', token })
}
