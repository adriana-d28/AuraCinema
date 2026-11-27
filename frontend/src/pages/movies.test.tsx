// The essential Phase 7.3 journeys: catalogue (Discover), movie details with
// rating and watchlist, and the Watchlist page; plus the Phase 7.4
// Recommendations page with Discovery Mode. They run through the real
// routes, guards and AuthProvider with a signed-in session. Only the network
// is replaced: fetch is a fake that answers like the backend
// (backend/app/api/routes/movies.py, ratings.py, watchlist.py and recommendations.py).
import { fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { routes } from '../app/routes'
import { AuthProvider, SESSION_STORAGE_KEY } from '../auth/AuthProvider'
import type { MovieDetails, MovieSummary } from '../services/api/types'

const ACCOUNT = { id: 7, email: 'ana@example.com', created_at: '2026-11-22T10:00:00Z', name: 'Ana', location: null, bio: null }

const HEAT: MovieSummary = {
  movie_id: 6,
  title: 'Heat (1995)',
  display_title: 'Heat',
  year: 1995,
  genres: ['Action', 'Crime', 'Thriller'],
  tmdb_id: 949,
  imdb_id: 113277,
  movielens_average_rating: 3.94,
  movielens_rating_count: 36213,
  poster_url: 'https://image.tmdb.org/t/p/w500/heat.jpg',
}
const MATRIX: MovieSummary = {
  ...HEAT,
  movie_id: 2571,
  title: 'Matrix, The (1999)',
  display_title: 'The Matrix',
  year: 1999,
  genres: ['Action', 'Sci-Fi', 'Thriller'],
  poster_url: null,
}
const HEAT_DETAILS: MovieDetails = {
  ...HEAT,
  overview: 'A master thief and a detective face each other in Los Angeles.',
  release_date: '1995-12-15',
  runtime: 170,
  poster_path: '/heat.jpg',
  metadata_status: 'available',
  metadata_updated_at: '2026-11-06T19:13:12Z',
  tmdb_validation_status: 'valid',
}

interface FakeRequest {
  method: string
  path: string
  query: URLSearchParams
  body: unknown
}

/** A fake backend: `answer` returns the response for each request; every request is recorded. */
function fakeBackend(answer: (request: FakeRequest) => Response | undefined) {
  const requests: FakeRequest[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const address = new URL(url)
      const request: FakeRequest = {
        method: init.method ?? 'GET',
        path: address.pathname.replace('/api/v1', ''),
        query: address.searchParams,
        body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
      }
      requests.push(request)
      if (request.path === '/users/me') return Response.json(ACCOUNT)
      const response = answer(request)
      if (!response) throw new Error(`Unexpected request: ${request.method} ${request.path}`)
      return response
    }),
  )
  return requests
}

function renderSignedIn(path: string) {
  sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token: 'token', expiresAt: Date.now() + 60_000 }))
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  )
  return router
}

const page = (items: MovieSummary[]) => Response.json({ items, total: items.length, limit: 20, offset: 0 })

afterEach(() => {
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('Discover catalogue', () => {
  it('shows the real catalogue and combines search and genre filters as the API expects', async () => {
    const requests = fakeBackend(({ path, query }) => {
      if (path === '/movies/featured') return Response.json(HEAT_DETAILS)
      if (path === '/movies/genres') return Response.json([{ genre: 'Action', movie_count: 900 }, { genre: 'Sci-Fi', movie_count: 300 }])
      if (path === '/movies') {
        if (query.get('search') === 'nothing') return page([])
        return page(query.get('genre') === 'Sci-Fi' ? [MATRIX] : [HEAT, MATRIX])
      }
    })
    const router = renderSignedIn('/')

    // Featured hero and catalogue grid, from the API; cards open the details page.
    expect(await screen.findByRole('heading', { level: 2, name: 'Heat' })).toBeInTheDocument()
    const catalogue = screen.getByRole('region', { name: 'From the archive' })
    expect(await within(catalogue).findByRole('link', { name: /The Matrix/ })).toHaveAttribute('href', '/movies/2571')

    // Search, then a genre: both are sent together, and the results are shown.
    fireEvent.change(screen.getByLabelText('Search movies by title'), { target: { value: 'matrix' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Sci-Fi' }))
    expect(await screen.findByText('Showing 1 of 1 films for “matrix” in Sci-Fi.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sci-Fi' })).toHaveAttribute('aria-pressed', 'true')
    const last = requests.filter((request) => request.path === '/movies').at(-1)
    expect(last?.query.get('search')).toBe('matrix')
    expect(last?.query.get('genre')).toBe('Sci-Fi')
    expect(router.state.location.search).toBe('?search=matrix&genre=Sci-Fi')

    // No match: a clear empty state with a way back to the full catalogue.
    fireEvent.change(screen.getByLabelText('Search movies by title'), { target: { value: 'nothing' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByRole('heading', { name: 'No films found' })).toBeInTheDocument()
  })
})

describe('Movie details', () => {
  it('shows the film, updates the rating and changes the watchlist independently', async () => {
    let ratingAttempts = 0
    const requests = fakeBackend(({ method, path, body }) => {
      if (path === '/movies/6/details') return Response.json(HEAT_DETAILS)
      if (path === '/ratings') return Response.json([{ movie_id: 6, rating: 3.5, created_at: '', rated_at: '', movie: HEAT }])
      if (path === '/watchlist') return Response.json([])
      if (method === 'PUT' && path === '/ratings/6') {
        ratingAttempts += 1
        if (ratingAttempts === 1) return Response.json({ detail: 'Service unavailable' }, { status: 503 })
        const { rating } = body as { rating: number }
        return Response.json({ movie_id: 6, rating, created_at: '', rated_at: '', movie: HEAT })
      }
      if (method === 'PUT' && path === '/watchlist/6') return Response.json({ movie_id: 6, added_at: '', movie: HEAT }, { status: 201 })
      if (method === 'DELETE' && path === '/watchlist/6') return new Response(null, { status: 204 })
    })
    renderSignedIn('/movies/6')

    // The film's data and the user's existing rating (3.5) are shown.
    expect(await screen.findByRole('heading', { level: 1, name: 'Heat' })).toBeInTheDocument()
    expect(screen.getByText(HEAT_DETAILS.overview as string)).toBeInTheDocument()
    expect(screen.getByText('2h 50m')).toBeInTheDocument()
    // The MovieLens community rating, kept apart from the user's own rating.
    expect(screen.getByText('MovieLens average rating: 3.9 out of 5, from 36,213 ratings')).toBeInTheDocument()
    expect(screen.getByText('Your rating: 3.5 out of 5.')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '3.5 stars' })).toBeChecked()

    // Update to 4.5: the first attempt fails and the saved rating stays 3.5.
    fireEvent.click(screen.getByRole('radio', { name: '4.5 stars' }))
    fireEvent.click(screen.getByRole('button', { name: 'Update rating' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your rating was not saved. Service unavailable')
    expect(screen.getByText('Your rating: 3.5 out of 5.')).toBeInTheDocument()

    // Second attempt succeeds: PUT {rating: 4.5}, and the page shows the new value.
    fireEvent.click(screen.getByRole('button', { name: 'Update rating' }))
    expect(await screen.findByText('Rating updated: 4.5 out of 5.')).toBeInTheDocument()
    expect(screen.getByText('Your rating: 4.5 out of 5.')).toBeInTheDocument()
    expect(requests.filter((request) => request.path === '/ratings/6').at(-1)?.body).toEqual({ rating: 4.5 })

    // Add to and remove from the watchlist; the rating is never touched.
    fireEvent.click(screen.getByRole('button', { name: 'Add to watchlist' }))
    expect(await screen.findByText('Added to your watchlist.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Remove from watchlist' }))
    expect(await screen.findByText('Removed from your watchlist.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to watchlist' })).toBeEnabled()
    expect(screen.getByText('Your rating: 4.5 out of 5.')).toBeInTheDocument()
    expect(requests.filter((request) => request.path === '/ratings/6')).toHaveLength(2) // Only the two rating saves.
  })

  it('shows "Film not found" for a film that is not in the catalogue', async () => {
    fakeBackend(({ path }) => {
      if (path === '/movies/999999/details') return Response.json({ detail: 'Movie not found' }, { status: 404 })
      if (path === '/ratings' || path === '/watchlist') return Response.json([])
    })
    renderSignedIn('/movies/999999')

    expect(await screen.findByRole('heading', { name: 'Film not found' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to Discover' })).toHaveAttribute('href', '/')
  })
})

describe('Profile recent ratings', () => {
  it("shows the user's ratings from the backend, newest first, with their stars", async () => {
    fakeBackend(({ path }) => {
      if (path === '/ratings') {
        return Response.json([
          { movie_id: 2571, rating: 5, created_at: '', rated_at: '', movie: MATRIX },
          { movie_id: 6, rating: 3.5, created_at: '', rated_at: '', movie: HEAT },
        ])
      }
    })
    renderSignedIn('/profile')

    const section = await screen.findByRole('region', { name: 'Recent ratings' })
    const links = await within(section).findAllByRole('link')
    expect(links.map((link) => link.getAttribute('href'))).toEqual(['/movies/2571', '/movies/6'])
    expect(within(section).getByRole('img', { name: 'Rated 3.5 out of 5' })).toBeInTheDocument()
  })
})

describe('Watchlist page', () => {
  it("lists the user's saved films, removes one and then shows the empty state", async () => {
    fakeBackend(({ method, path }) => {
      if (path === '/watchlist') return Response.json([{ movie_id: 6, added_at: '', movie: HEAT }])
      if (method === 'DELETE' && path === '/watchlist/6') return new Response(null, { status: 204 })
    })
    renderSignedIn('/watchlist')

    expect(await screen.findByRole('link', { name: /Heat/ })).toHaveAttribute('href', '/movies/6')
    fireEvent.click(screen.getByRole('button', { name: 'Remove Heat from your watchlist' }))

    expect(await screen.findByRole('heading', { name: 'Your watchlist is empty' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Heat was removed from your watchlist.')
  })

  it('ends the session when the backend rejects the token (401)', async () => {
    fakeBackend(({ path }) => {
      if (path === '/watchlist') return Response.json({ detail: 'Could not validate credentials' }, { status: 401 })
    })
    renderSignedIn('/watchlist')

    expect(await screen.findByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Your session has ended.')
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })
})

describe('Recommendations page', () => {
  const recommended = (movie: MovieSummary, rank: number) => ({ ...movie, rank, score: 1 / rank })

  it('shows the plain personalised list first, and Discovery Mode can be turned on, changed and off', async () => {
    let attempts = 0
    const requests = fakeBackend(({ path, query }) => {
      if (path !== '/recommendations') return undefined
      attempts += 1
      if (attempts === 1) return Response.json({ detail: 'Recommendations are temporarily unavailable' }, { status: 503 })
      const mode = query.get('discovery_mode')
      const items = mode === 'adventurous' ? [recommended(HEAT, 1)] : [recommended(MATRIX, 1), recommended(HEAT, 2)]
      return Response.json({ source: 'collaborative_filtering', personalized: true, message: null, discovery_mode: mode, items })
    })
    const router = renderSignedIn('/recommendations')
    const discoverySwitch = () => screen.getByRole('switch', { name: 'Discovery Mode' })
    const listLinks = () =>
      within(screen.getByRole('list', { name: 'Recommended films, best first' })).getAllByRole('link')

    // The service is unavailable at first; "Try again" repeats the request.
    expect(await screen.findByRole('heading', { name: 'Recommendations are temporarily unavailable' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))

    // Discovery Mode starts OFF: plain personalised list, no mode sent, no mode options shown.
    expect(await screen.findByText('Personalised')).toBeInTheDocument()
    expect(listLinks().map((link) => link.getAttribute('href'))).toEqual(['/movies/2571', '/movies/6'])
    expect(requests.at(-1)?.query.has('discovery_mode')).toBe(false)
    expect(discoverySwitch()).toHaveAttribute('aria-checked', 'false')
    expect(screen.queryByRole('radio', { name: 'Balanced' })).not.toBeInTheDocument()

    // Turned on: Balanced is the default mode.
    fireEvent.click(discoverySwitch())
    expect(await screen.findByText('Personalised · Balanced')).toBeInTheDocument()
    expect(requests.at(-1)?.query.get('discovery_mode')).toBe('balanced')
    expect(screen.getByRole('radio', { name: 'Balanced' })).toBeChecked()

    // Adventurous: a new request, a new list, and the mode kept in the address.
    fireEvent.click(screen.getByRole('radio', { name: 'Adventurous' }))
    expect(await screen.findByText('Personalised · Adventurous')).toBeInTheDocument()
    expect(requests.at(-1)?.query.get('discovery_mode')).toBe('adventurous')
    expect(listLinks()).toHaveLength(1)
    expect(router.state.location.search).toBe('?mode=adventurous')

    // Turned off again: back to the plain list.
    fireEvent.click(discoverySwitch())
    expect(await screen.findByText('Personalised')).toBeInTheDocument()
    expect(requests.at(-1)?.query.has('discovery_mode')).toBe(false)
    expect(router.state.location.search).toBe('')
  })

  it('explains cold-start recommendations and disables the Discovery Mode switch', async () => {
    fakeBackend(({ path }) => {
      if (path === '/recommendations') {
        return Response.json({
          source: 'popularity',
          personalized: false,
          message: 'Discover popular movies while we get to know your taste!',
          discovery_mode: null,
          items: [recommended(HEAT, 1)],
        })
      }
    })
    renderSignedIn('/recommendations')

    expect(await screen.findByText('Discover popular movies while we get to know your taste!')).toBeInTheDocument()
    expect(screen.getByText('Popular picks')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Discovery Mode' })).toBeDisabled()
    expect(screen.queryByRole('radio', { name: 'Safe' })).not.toBeInTheDocument()
    expect(screen.getByText('Available once your recommendations are personalised.')).toBeInTheDocument()
  })
})
