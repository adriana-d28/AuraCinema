// Keeps track of who is signed in, for the whole application.
//
// How the session works (backend contract: backend/app/api/routes/auth.py):
//   - POST /auth/login returns a JWT access token and its lifetime in seconds
//     (expires_in, 60 minutes by default). There is no refresh token and no
//     logout endpoint, so the token simply stops working when it expires.
//   - Only the token and its expiry time are stored, in sessionStorage. They
//     survive a page refresh but are removed when the browser tab is closed.
//     The password is never stored.
//   - On start-up a stored, unexpired token is checked with GET /users/me.
//     A 401 (invalid, expired or deleted account) or any other failure ends
//     the session, so the frontend never shows a session the backend rejects.
//   - A timer ends the session at the moment the token expires.
//   - A 401 on any later authenticated request (ratings, watchlist) also ends
//     it, through the handler registered in services/api/client.ts.
//   - Logging out forgets the token in this browser. The token itself is not
//     revoked by the backend; it stays technically valid until it expires.

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { getCurrentUser, loginRequest } from '../services/api/auth'
import { setUnauthorizedHandler } from '../services/api/client'
import type { User } from '../services/api/types'
import { AuthContext, type AuthContextValue, type AuthStatus, type SessionEndReason } from './authContext'

export const SESSION_STORAGE_KEY = 'auracinema.session'

interface StoredSession {
  token: string
  /** Moment the token expires, in milliseconds since 1970 (Date.now() format). */
  expiresAt: number
}

interface AuthState {
  status: AuthStatus
  session: StoredSession | null
  user: User | null
  endReason: SessionEndReason | null
}

function readStoredSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_STORAGE_KEY)
    if (raw === null) return null
    const parsed = JSON.parse(raw) as Partial<StoredSession>
    if (typeof parsed.token === 'string' && typeof parsed.expiresAt === 'number') {
      return { token: parsed.token, expiresAt: parsed.expiresAt }
    }
  } catch {
    // Storage blocked or the value is not valid JSON: treat it as no session.
  }
  clearStoredSession()
  return null
}

function storeSession(session: StoredSession) {
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session))
  } catch {
    // Storage unavailable (e.g. blocked): the session still works until a refresh.
  }
}

function clearStoredSession() {
  try {
    sessionStorage.removeItem(SESSION_STORAGE_KEY)
  } catch {
    // Nothing to remove.
  }
}

/** The state when the application starts, based on what is stored. */
function initialState(): AuthState {
  const stored = readStoredSession()
  if (stored === null) {
    return { status: 'anonymous', session: null, user: null, endReason: null }
  }
  if (stored.expiresAt <= Date.now()) {
    clearStoredSession()
    return { status: 'anonymous', session: null, user: null, endReason: 'expired' }
  }
  return { status: 'initialising', session: stored, user: null, endReason: null }
}

const signedOut = (endReason: SessionEndReason): AuthState => ({
  status: 'anonymous',
  session: null,
  user: null,
  endReason,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(initialState)

  const endSession = useCallback((reason: SessionEndReason) => {
    clearStoredSession()
    setState(signedOut(reason))
  }, [])

  // Any authenticated request answered with 401 (Phase 7.3: ratings,
  // watchlist) ends the session in the same way as an expired token.
  useEffect(() => {
    setUnauthorizedHandler(() => endSession('expired'))
    return () => setUnauthorizedHandler(null)
  }, [endSession])

  // Start-up: check a stored token with the backend before trusting it.
  const pendingToken = state.status === 'initialising' ? state.session?.token : undefined
  useEffect(() => {
    if (pendingToken === undefined) return
    const controller = new AbortController()
    getCurrentUser(pendingToken, controller.signal)
      .then((user) => setState((current) => ({ ...current, status: 'authenticated', user })))
      .catch((error: unknown) => {
        // Cancelled because the component was removed: nothing to do.
        if (error instanceof DOMException && error.name === 'AbortError') return
        endSession('expired')
      })
    return () => controller.abort()
  }, [pendingToken, endSession])

  // End the session when the token expires.
  const expiresAt = state.status === 'authenticated' ? state.session?.expiresAt : undefined
  useEffect(() => {
    if (expiresAt === undefined) return
    const timer = window.setTimeout(() => endSession('expired'), Math.max(0, expiresAt - Date.now()))
    return () => window.clearTimeout(timer)
  }, [expiresAt, endSession])

  const login = useCallback(async (email: string, password: string) => {
    const tokenResponse = await loginRequest(email, password)
    // The login response holds only the token, so the account (name, email)
    // is loaded straight away for the header.
    const user = await getCurrentUser(tokenResponse.access_token)
    const session: StoredSession = {
      token: tokenResponse.access_token,
      expiresAt: Date.now() + tokenResponse.expires_in * 1000,
    }
    storeSession(session)
    setState({ status: 'authenticated', session, user, endReason: null })
  }, [])

  const logout = useCallback(() => endSession('logout'), [endSession])

  const value = useMemo<AuthContextValue>(
    () => ({
      status: state.status,
      user: state.user,
      token: state.status === 'authenticated' ? (state.session?.token ?? null) : null,
      endReason: state.endReason,
      login,
      logout,
    }),
    [state, login, logout],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
