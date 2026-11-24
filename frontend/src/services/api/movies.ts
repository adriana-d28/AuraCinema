// Catalogue endpoints (backend/app/api/routes/movies.py). They are public, so
// no token is sent:
//   - GET /movies?search=&genre=&limit=&offset=  -> MovieListResponse (ordered by title)
//   - GET /movies/genres                          -> Genre[]
//   - GET /movies/featured                        -> MovieDetails (404 when none qualifies)
//   - GET /movies/{id}/details                    -> MovieDetails (404 unknown movie)

import { apiRequest } from './client'
import type { Genre, MovieDetails, MovieListResponse } from './types'

/** Number of movies loaded per catalogue page (the backend default). */
export const CATALOGUE_PAGE_SIZE = 20

export interface CatalogueQuery {
  search?: string
  genre?: string
  offset?: number
}

export function listMovies(query: CatalogueQuery, signal?: AbortSignal): Promise<MovieListResponse> {
  const params = new URLSearchParams({ limit: String(CATALOGUE_PAGE_SIZE), offset: String(query.offset ?? 0) })
  // Empty values are left out: the backend rejects an empty ?search= or ?genre=.
  if (query.search) params.set('search', query.search)
  if (query.genre) params.set('genre', query.genre)
  return apiRequest<MovieListResponse>(`/movies?${params}`, { signal })
}

export function listGenres(signal?: AbortSignal): Promise<Genre[]> {
  return apiRequest<Genre[]>('/movies/genres', { signal })
}

export function getFeaturedMovie(signal?: AbortSignal): Promise<MovieDetails> {
  return apiRequest<MovieDetails>('/movies/featured', { signal })
}

export function getMovieDetails(movieId: number, signal?: AbortSignal): Promise<MovieDetails> {
  return apiRequest<MovieDetails>(`/movies/${movieId}/details`, { signal })
}
