// Rating endpoints (backend/app/api/routes/ratings.py). Login required: every
// call acts only on the signed-in user's own ratings.
//   - GET    /ratings             -> Rating[] (most recent first)
//   - PUT    /ratings/{movie_id}  JSON {rating} -> Rating (201 created / 200 updated)
//   - DELETE /ratings/{movie_id}  -> 204 (404 when the movie was not rated)
// There is no "get one rating" endpoint, so a page that needs the rating of
// one movie looks it up in the list.

import { apiRequest } from './client'
import type { Rating } from './types'

export function listMyRatings(token: string, signal?: AbortSignal): Promise<Rating[]> {
  return apiRequest<Rating[]>('/ratings', { token, signal })
}

/** Create or update (PUT is idempotent) the rating: 0.5 to 5.0 in steps of 0.5. */
export function saveRating(token: string, movieId: number, rating: number): Promise<Rating> {
  return apiRequest<Rating>(`/ratings/${movieId}`, { method: 'PUT', body: { rating }, token })
}

export function deleteRating(token: string, movieId: number): Promise<void> {
  return apiRequest<void>(`/ratings/${movieId}`, { method: 'DELETE', token })
}
