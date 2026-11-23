// The shared authentication state and the hook pages use to read it.
//
// The state itself is created by <AuthProvider> (AuthProvider.tsx). This file
// only holds the context object and its type, so the provider file exports a
// component only (fast-refresh rule in .oxlintrc.json).

import { createContext, useContext } from 'react'
import type { User } from '../services/api/types'

/**
 * - initialising:  a stored token was found and is being checked with GET /users/me;
 * - authenticated: the token is valid and the user's account is known;
 * - anonymous:     nobody is signed in.
 */
export type AuthStatus = 'initialising' | 'authenticated' | 'anonymous'

/** Why the last session ended: the user logged out, or the token expired / was rejected. */
export type SessionEndReason = 'logout' | 'expired'

export interface AuthContextValue {
  status: AuthStatus
  user: User | null
  /** The access token, to pass to apiRequest({ token }) in authenticated requests. */
  token: string | null
  endReason: SessionEndReason | null
  /** Log in with the backend; rejects with an ApiError when it fails. */
  login: (email: string, password: string) => Promise<void>
  /** Forget the session on this device (the backend has no logout endpoint). */
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth must be used inside <AuthProvider>.')
  }
  return value
}
