// Checks routing and the shared navigation together, using the real route
// list inside an in-memory router (no browser address bar needed).
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { routes } from './routes'

describe('application routes', () => {
  it('renders the page for the address inside the shared layout and navigation', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/recommendations'] })
    render(<RouterProvider router={router} />)

    // The matching page is rendered.
    expect(screen.getByRole('heading', { level: 1, name: 'Your recommendations' })).toBeInTheDocument()

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
