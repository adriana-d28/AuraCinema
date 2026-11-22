// Application-wide configuration values.
//
// Vite reads variables that start with VITE_ from the environment or from a
// `.env` file (see .env.example) and makes them available as import.meta.env.
// When nothing is configured we fall back to the local backend address used
// during development, so `npm run dev` works without any extra set-up.

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/api/v1'

// Remove a trailing slash so paths can always be joined as `${base}${path}`.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  '',
)

// Notice required by TMDB's terms of use, shown in the footer. It must be
// displayed word for word (frontend/docs/frontend_requirements.md, FR-1).
export const TMDB_ATTRIBUTION_NOTICE =
  'This product uses the TMDB API but is not endorsed or certified by TMDB.'
