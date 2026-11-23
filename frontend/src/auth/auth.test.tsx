// The essential authentication journeys, run through the real routes, guards,
// pages and AuthProvider. Only the network is replaced: fetch is a fake that
// answers like the backend (backend/app/api/routes/auth.py and users.py).
import { act, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { routes } from '../app/routes'
import { AuthProvider, SESSION_STORAGE_KEY } from './AuthProvider'

const ACCOUNT = { id: 7, email: 'ana@example.com', created_at: '2026-11-22T10:00:00Z', name: 'Ana', location: null, bio: null }
const PASSWORD = 'a long enough password'

/** A fake backend: `answers` maps an endpoint path to its response. */
function fakeBackend(answers: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (url: string) => {
    const path = new URL(url).pathname.replace('/api/v1', '')
    const answer = answers[path]
    if (!answer) throw new Error(`Unexpected request to ${path}`)
    return answer()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  )
  return router
}

function fillIn(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('authentication', () => {
  it('sends a signed-out visitor to Log in and back to the requested page after a successful login', async () => {
    const fetchMock = fakeBackend({
      '/auth/login': () => Response.json({ access_token: 'new-token', token_type: 'bearer', expires_in: 3600 }),
      '/users/me': () => Response.json(ACCOUNT),
    })
    renderApp('/watchlist')

    // The protected page is not shown; Log in is.
    expect(screen.getByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Your watchlist' })).not.toBeInTheDocument()

    fillIn('Email', 'ana@example.com')
    fillIn('Password', PASSWORD)
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    // Back on the page originally requested, signed in as Ana.
    expect(await screen.findByRole('heading', { level: 1, name: 'Your watchlist' })).toBeInTheDocument()
    expect(screen.getByText('Ana')).toBeInTheDocument()

    // The login was sent as the OAuth2 form the backend expects.
    const [, loginInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect((loginInit.body as URLSearchParams).get('username')).toBe('ana@example.com')
    // Only the token and its expiry are stored, never the password.
    const stored = sessionStorage.getItem(SESSION_STORAGE_KEY) ?? ''
    expect(JSON.parse(stored).token).toBe('new-token')
    expect(stored).not.toContain(PASSWORD)
  })

  it('shows the error and stays on Log in when the credentials are rejected', async () => {
    fakeBackend({
      '/auth/login': () => Response.json({ detail: 'Incorrect email or password' }, { status: 401 }),
    })
    renderApp('/login')

    fillIn('Email', 'ana@example.com')
    fillIn('Password', 'wrong password')
    fireEvent.click(screen.getByRole('button', { name: 'Log in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(screen.getByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log in' })).toBeEnabled()
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })

  it('creates an account and then opens Log in with a confirmation', async () => {
    const fetchMock = fakeBackend({ '/auth/register': () => Response.json(ACCOUNT, { status: 201 }) })
    renderApp('/register')

    fillIn('Name', 'Ana')
    fillIn('Email', 'ana@example.com')
    fillIn('Password', PASSWORD)
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByRole('status')).toHaveTextContent('Account created.')
    expect(screen.getByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveValue('ana@example.com')

    // The body matches RegisterRequest exactly (the backend forbids extra fields).
    const [, registerInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(registerInit.body as string)).toEqual({ name: 'Ana', email: 'ana@example.com', password: PASSWORD })
  })

  it('logs out: forgets the session and protects the application pages again', async () => {
    sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify({ token: 'stored-token', expiresAt: Date.now() + 60_000 }))
    fakeBackend({ '/users/me': () => Response.json(ACCOUNT) })
    const router = renderApp('/watchlist')

    expect(await screen.findByRole('heading', { level: 1, name: 'Your watchlist' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('You have logged out.')
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()

    // Opening a protected page directly still leads to Log in.
    await router.navigate('/settings')
    expect(screen.getByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
  })

  it('cancels the expiry timer on log out and starts a single new one for the next session', async () => {
    // Fake clock (setTimeout and Date). shouldAdvanceTime keeps it moving with
    // real time, so Testing Library's waiting helpers still work.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const ONE_HOUR = 3600
    const lifetimes = [ONE_HOUR, 2 * ONE_HOUR] // Session A: 1 h, session B: 2 h.
    fakeBackend({
      '/auth/login': () =>
        Response.json({ access_token: 'token', token_type: 'bearer', expires_in: lifetimes.shift() }),
      '/users/me': () => Response.json(ACCOUNT),
    })
    renderApp('/login')

    async function logIn() {
      fillIn('Email', 'ana@example.com')
      fillIn('Password', PASSWORD)
      fireEvent.click(screen.getByRole('button', { name: 'Log in' }))
      expect(await screen.findByRole('heading', { level: 1, name: 'Discover movies' })).toBeInTheDocument()
    }

    await logIn() // Session A starts its 1-hour timer.
    fireEvent.click(screen.getByRole('button', { name: 'Log out' })) // Must cancel it.
    expect(await screen.findByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    await logIn() // Session B starts a 2-hour timer.

    // Past session A's expiry: a leftover (duplicate) timer would end session B here.
    await act(async () => {
      vi.advanceTimersByTime((ONE_HOUR + 60) * 1000)
    })
    expect(screen.getByRole('heading', { level: 1, name: 'Discover movies' })).toBeInTheDocument()

    // Past session B's expiry: its own timer ends the session.
    await act(async () => {
      vi.advanceTimersByTime(ONE_HOUR * 1000)
    })
    expect(await screen.findByRole('heading', { level: 1, name: 'Log in' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Your session has ended.')
    expect(sessionStorage.getItem(SESSION_STORAGE_KEY)).toBeNull()
  })
})
