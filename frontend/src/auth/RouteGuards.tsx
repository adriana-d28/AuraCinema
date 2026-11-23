// Route protection, used in routes.tsx around the two layouts.
//
// - RequireAuth wraps the application pages: signed-out visitors are sent to
//   /login. The page they asked for is kept in the router's location state
//   (never in the URL), so after logging in they return to it. That value
//   always comes from the router itself, so it can only be an in-app path.
// - RedirectIfAuthenticated wraps Login and Register: signed-in users go to
//   that saved page, or to Discover.
// While a stored token is still being checked, neither renders anything, so
// no protected page flashes and no redirect happens too early.

import type { ReactNode } from 'react'
import { Navigate, useLocation, type Location } from 'react-router'
import { useAuth } from './authContext'

/** Location state passed to /login by RequireAuth. */
export interface LoginRedirectState {
  from?: Location
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, endReason } = useAuth()
  const location = useLocation()

  if (status === 'initialising') return null
  if (status === 'anonymous') {
    // After a deliberate log out the next sign-in starts at Discover, so the
    // previous user's last page is not remembered.
    const state: LoginRedirectState | undefined = endReason === 'logout' ? undefined : { from: location }
    return <Navigate to="/login" replace state={state} />
  }
  return children
}

export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'initialising') return null
  if (status === 'authenticated') {
    const from = (location.state as LoginRedirectState | null)?.from
    const destination = from ? `${from.pathname}${from.search}${from.hash}` : '/'
    return <Navigate to={destination} replace />
  }
  return children
}
