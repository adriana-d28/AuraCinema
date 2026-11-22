// TypeScript versions of the data returned by the AuraCinema backend.
//
// Each type mirrors a Pydantic schema in backend/app/schemas/. The field names
// stay in snake_case, exactly as the API sends them, so no conversion layer is
// needed. If a backend schema changes, the matching type here must change too.
//
// Nothing in this file calls the API: these are only descriptions of the data.

// ---------- Movies (backend/app/schemas/movie.py) ----------

/** Why the stored TMDB metadata is (or is not) available for a movie. */
export type MetadataStatus =
  | 'available' // Metadata was imported from TMDB.
  | 'no_tmdb_id' // The movie has no TMDB ID in the catalogue.
  | 'not_imported' // The refresh script has not processed this movie yet.
  | 'not_found' // TMDB answered 404 for this TMDB ID.
  | 'lookup_failed' // The last lookup failed temporarily.

/** Core catalogue data (MovieRead). The title includes the year, e.g. "Heat (1995)". */
export interface Movie {
  movie_id: number
  title: string
  genres: string[]
  tmdb_id: number | null
  imdb_id: number | null
}

/** One page of catalogue results (MovieListResponse), from GET /movies. */
export interface MovieListResponse {
  items: Movie[]
  total: number
  limit: number
  offset: number
}

/** A movie plus its stored TMDB metadata (MovieDetailsRead), from GET /movies/{id}/details. */
export interface MovieDetails extends Movie {
  overview: string | null
  release_date: string | null // ISO date, e.g. "1995-12-15"
  runtime: number | null // minutes
  poster_path: string | null
  poster_url: string | null // null means: show the poster placeholder
  metadata_status: MetadataStatus
  metadata_updated_at: string | null // ISO date-time
  tmdb_validation_status: string
}

// ---------- Recommendations (backend/app/schemas/recommendation.py) ----------

/** Which recommender produced the list. Decided by the backend, never by the frontend. */
export type RecommendationSource = 'collaborative_filtering' | 'popularity'

/** One recommended movie (RecommendedMovieRead). Use `rank` for ordering, not `score`. */
export interface RecommendedMovie extends Movie {
  rank: number
  score: number
  poster_url: string | null
}

/** Response of GET /recommendations (login required). */
export interface RecommendationResponse {
  source: RecommendationSource
  personalized: boolean
  message: string | null // Cold-start message when source is "popularity"
  items: RecommendedMovie[]
}

// ---------- Accounts (backend/app/schemas/auth.py and user.py) ----------

/** Response of POST /auth/register and GET /users/me. */
export interface User {
  id: number
  email: string
  created_at: string
}

/** Response of POST /auth/login (sent as a form, not JSON: username = email). */
export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number // seconds
}

// ---------- Ratings and watchlist (backend/app/schemas/rating.py, watchlist.py) ----------

/** One of the user's ratings. Ratings go from 0.5 to 5.0 in steps of 0.5. */
export interface Rating {
  movie_id: number
  rating: number
  created_at: string
  rated_at: string
}

/** One watchlist entry. The API currently returns only the movie ID and the date. */
export interface WatchlistItem {
  movie_id: number
  added_at: string
}
