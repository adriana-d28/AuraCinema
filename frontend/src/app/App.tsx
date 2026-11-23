// The root component: it turns the route list into a working browser router.
//
// createBrowserRouter uses real browser addresses (e.g. /watchlist), so the
// Back and Forward buttons and bookmarks work as users expect.
// RouterProvider renders the layout and page that match the current address.
// AuthProvider sits outside the router, so every page and route guard can
// read the signed-in user (src/auth/).

import { createBrowserRouter, RouterProvider } from 'react-router'
import { AuthProvider } from '../auth/AuthProvider'
import { routes } from './routes'

const router = createBrowserRouter(routes)

export function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
}
