// Checks routing and the shared navigation together, using the real route
// list inside an in-memory router (no browser address bar needed).
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, SESSION_STORAGE_KEY } from '../auth/AuthProvider'
import { routes } from './routes'

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('application routes', () => {
  it('renders the page for the address inside the shared layout and navigation', async () => {
    // The application pages are protected (Phase 7.2): start with a stored
    // session that GET /users/me accepts.
    sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ token: 'stored-token', expiresAt: Date.now() + 60_000 }),
    )
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json({ id: 1, email: 'ana@example.com', created_at: '', name: 'Ana', location: null, bio: null }),
      ),
    )
    const router = createMemoryRouter(routes, { initialEntries: ['/recommendations'] })
    render(
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>,
    )

    // The matching page is rendered.
    expect(await screen.findByRole('heading', { level: 1, name: 'Your recommendations' })).toBeInTheDocument()

    // The main navigation has exactly the four first-iteration sections
    // (no Taste Evolution), and marks the current page.
    const navigation = screen.getByRole('navigation', { name: 'Main' })
    const links = within(navigation)
      .getAllByRole('listitem')
      .map((item) => within(item).getByRole('link'))
    expect(links.map((link) => link.textContent)).toEqual(['Discover', 'Recommendations', 'Watchlist', 'Profile'])
    expect(within(navigation).getByRole('link', { name: 'Recommendations' })).toHaveAttribute('aria-current', 'page')
  })
})
