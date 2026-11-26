// A small, reusable helper for talking to the AuraCinema backend.
//
// It uses the browser's built-in fetch(), so no extra library (such as axios)
// is needed. It takes care of the parts every request has in common:
//   - joining the base URL from config.ts with the endpoint path;
//   - sending and reading JSON;
//   - adding the login token when one is given;
//   - turning an unsuccessful answer into a clear ApiError.
//
// Endpoint functions live next to this file (auth.ts, movies.ts, ratings.ts,
// watchlist.ts) and use only endpoints that really exist in
// backend/app/api/routes/. Authenticated calls pass useAuth().token.

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
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  /**
   * Data to send. Plain objects are sent as JSON; URLSearchParams as a form
   * (used by login); FormData as multipart (used by the picture upload).
   */
  body?: unknown
  /** Login token. When present it is sent as "Authorization: Bearer <token>". */
  token?: string | null
  /** Lets a page cancel a request it no longer needs (for example when the user leaves). */
  signal?: AbortSignal
  /** Read the answer as a Blob (an image) instead of JSON. */
  responseType?: 'json' | 'blob'
}

// Called when an authenticated request answers 401. AuthProvider registers a
// function that ends the session, so the user is sent back to Log in.
let unauthorizedHandler: (() => void) | null = null

/** Register (or clear, with null) the function called after a 401 on an authenticated request. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  unauthorizedHandler = handler
}

/**
 * Send a request to the backend and return the response body.
 *
 * Example:
 *   const details = await apiRequest<MovieDetails>('/movies/6/details')
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, token, signal, responseType = 'json' } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  let requestBody: BodyInit | undefined

  if (body instanceof URLSearchParams || body instanceof FormData) {
    // Form data: fetch sets the right Content-Type header (and, for a
    // multipart upload, its boundary) by itself.
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
    // A token was sent but the backend rejected it (expired, invalid, deleted
    // account): the session is over. Handled once here instead of in every page.
    if (response.status === 401 && token) unauthorizedHandler?.()
    throw new ApiError(response.status, await readErrorMessage(response))
  }

  // 204 No Content (e.g. after a DELETE) has no body to read.
  if (response.status === 204) {
    return undefined as T
  }
  if (responseType === 'blob') {
    return (await response.blob()) as T
  }
  return (await response.json()) as T
}

/** True when a request was cancelled on purpose (the page no longer needs it). */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

/** A message that can be shown to the user for any error thrown by a request. */
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Something went wrong. Please try again.'
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
