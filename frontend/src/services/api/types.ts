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

/** Core catalogue data (MovieRead). `title` is the original MovieLens title, e.g. "Matrix, The (1999)". */
export interface Movie {
  movie_id: number
  title: string
  /** Readable title prepared by the backend, e.g. "The Matrix". Use this one on screen. */
  display_title: string
  /** Year taken from the MovieLens title, or null when there is none. */
  year: number | null
  genres: string[]
  tmdb_id: number | null
  imdb_id: number | null
}

/** A movie as shown in lists (MovieSummaryRead): catalogue pages, watchlist, ratings. */
export interface MovieSummary extends Movie {
  poster_url: string | null // null means: show the poster placeholder
}

/** One page of catalogue results (MovieListResponse), from GET /movies. */
export interface MovieListResponse {
  items: MovieSummary[]
  total: number // Matching movies over all pages
  limit: number
  offset: number
}

/** A movie plus its stored TMDB metadata (MovieDetailsRead), from GET /movies/{id}/details and /movies/featured. */
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

/** One catalogue genre (GenreRead), from GET /movies/genres. `genre` is the value for ?genre=. */
export interface Genre {
  genre: string
  movie_count: number
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

/** How adventurous personalised recommendations are (the ?discovery_mode= value). */
export type DiscoveryMode = 'safe' | 'balanced' | 'adventurous'

/** Response of GET /recommendations (login required). */
export interface RecommendationResponse {
  source: RecommendationSource
  personalized: boolean
  message: string | null // Cold-start message when source is "popularity"
  discovery_mode: DiscoveryMode | null // null when Discovery Mode is off, and for popularity results
  items: RecommendedMovie[]
}

// ---------- Accounts (backend/app/schemas/auth.py and user.py) ----------

/** Response of POST /auth/register and GET /users/me (UserRead). */
export interface User {
  id: number
  email: string
  created_at: string
  // `name` is null only for accounts created before names were required.
  name: string | null
  location: string | null
  bio: string | null
}

/** Body of POST /auth/register (RegisterRequest). The backend rejects any other field. */
export interface RegisterRequest {
  name: string // 1-100 characters after trimming
  email: string
  password: string // 15-128 characters
}

/** Response of POST /auth/login (sent as a form, not JSON: username = email). */
export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number // seconds
}

// ---------- Ratings and watchlist (backend/app/schemas/rating.py, watchlist.py) ----------

/** One of the user's ratings (RatingRead). Ratings go from 0.5 to 5.0 in steps of 0.5. */
export interface Rating {
  movie_id: number
  rating: number
  created_at: string
  rated_at: string
  movie: MovieSummary
}

/** One watchlist entry (WatchlistItemRead), with the movie as shown in lists. */
export interface WatchlistItem {
  movie_id: number
  added_at: string
  movie: MovieSummary
}
