// A small, reusable helper for talking to the AuraCinema backend.
//
// It uses the browser's built-in fetch(), so no extra library (such as axios)
// is needed. It takes care of the parts every request has in common:
//   - joining the base URL from config.ts with the endpoint path;
//   - sending and reading JSON;
//   - adding the login token when one is given;
//   - turning an unsuccessful answer into a clear ApiError.
//
// Endpoint functions live next to this file (auth.ts since Phase 7.2) and are
// added in the phases that need them, using only endpoints that really exist
// in backend/app/api/routes/. Authenticated calls pass useAuth().token.

import { API_BASE_URL } from '../../config'

/** Error thrown when the backend answers with an error status (4xx or 5xx). */
export class ApiError extends Error {
  /** HTTP status code, e.g. 401, 404, 422 or 503. */
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  /** Data to send. Plain objects are sent as JSON; URLSearchParams as a form (used by login). */
  body?: unknown
  /** Login token. When present it is sent as "Authorization: Bearer <token>". */
  token?: string | null
  /** Lets a page cancel a request it no longer needs (for example when the user leaves). */
  signal?: AbortSignal
}

/**
 * Send a request to the backend and return the response body.
 *
 * Example (in a later phase):
 *   const details = await apiRequest<MovieDetails>('/movies/6/details')
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  let requestBody: BodyInit | undefined

  if (body instanceof URLSearchParams) {
    // Form data: fetch sets the right Content-Type header by itself.
    requestBody = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    requestBody = JSON.stringify(body)
  }

  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { method, headers, body: requestBody, signal })
  } catch (error) {
    // Cancelled on purpose: let the caller see the original AbortError.
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    // Network problem (backend not running, no connection...): status 0 means "no answer".
    throw new ApiError(0, 'Could not reach the AuraCinema server. Please try again.')
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response))
  }

  // 204 No Content (e.g. after a DELETE) has no body to read.
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

/**
 * Get a human-readable message from a FastAPI error response.
 * FastAPI sends {"detail": "text"} for most errors and
 * {"detail": [{"msg": "..."}, ...]} for validation errors (422).
 */
async function readErrorMessage(response: Response): Promise<string> {
  const fallback = `Request failed (HTTP ${response.status}).`
  try {
    const data: unknown = await response.json()
    const detail = (data as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (item as { msg?: unknown }).msg)
        .filter((msg): msg is string => typeof msg === 'string')
      if (messages.length > 0) return messages.join(' ')
    }
  } catch {
    // The body was not JSON: use the generic message below.
  }
  return fallback
}
