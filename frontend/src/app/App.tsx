// The root component: it turns the route list into a working browser router.
//
// createBrowserRouter uses real browser addresses (e.g. /watchlist), so the
// Back and Forward buttons and bookmarks work as users expect.
// RouterProvider renders the layout and page that match the current address.

import { createBrowserRouter, RouterProvider } from 'react-router'
import { routes } from './routes'

const router = createBrowserRouter(routes)

export function App() {
  return <RouterProvider router={router} />
}
