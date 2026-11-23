// The map of the application: which address shows which page.
//
// Two groups of pages share two different frames ("layouts"):
//   - AuthLayout: Register and Log in (two-column introduction + form);
//   - AppLayout:  every other page (header with navigation + footer).
// A layout route has no "path" of its own; it only wraps its children, and
// the child page appears where the layout renders <Outlet />.
//
// Taste Evolution is not part of the first iteration, so it has no route.
// Route protection (Phase 7.2, src/auth/RouteGuards.tsx): every AppLayout page
// needs a signed-in user; Login and Register are for signed-out visitors only.
//
// The list is kept separate from App.tsx so the tests can load exactly the
// same routes inside an in-memory router.

import type { RouteObject } from 'react-router'
import { RedirectIfAuthenticated, RequireAuth } from '../auth/RouteGuards'
import { AppLayout } from '../components/layout/AppLayout'
import { AuthLayout } from '../components/layout/AuthLayout'
import { DiscoverPage } from '../pages/DiscoverPage'
import { LoginPage } from '../pages/LoginPage'
import { MovieDetailsPage } from '../pages/MovieDetailsPage'
import { NotFoundPage } from '../pages/NotFoundPage'
import { ProfilePage } from '../pages/ProfilePage'
import { RecommendationsPage } from '../pages/RecommendationsPage'
import { RegisterPage } from '../pages/RegisterPage'
import { SettingsPage } from '../pages/SettingsPage'
import { WatchlistPage } from '../pages/WatchlistPage'

export const routes: RouteObject[] = [
  {
    element: (
      <RedirectIfAuthenticated>
        <AuthLayout />
      </RedirectIfAuthenticated>
    ),
    children: [
      { path: 'login', element: <LoginPage /> },
      { path: 'register', element: <RegisterPage /> },
    ],
  },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <DiscoverPage /> }, // "/" = Discover
      { path: 'recommendations', element: <RecommendationsPage /> },
      { path: 'watchlist', element: <WatchlistPage /> },
      { path: 'profile', element: <ProfilePage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'movies/:movieId', element: <MovieDetailsPage /> },
      { path: '*', element: <NotFoundPage /> }, // Any other address
    ],
  },
]
