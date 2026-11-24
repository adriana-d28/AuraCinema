// Watchlist: films the user has saved to watch later.
//
// GET /watchlist returns the user's entries, newest first, each with the
// movie summary (title, year, genres, poster), so no extra request per film is
// needed. Each film is a compact MovieCard (opens the details page) with its
// own "Remove" button next to it (a button cannot sit inside the card's link).
// After a successful DELETE the film is simply taken out of the list on screen.
//
// Removing a film from the watchlist never changes its rating.

import { useEffect, useState } from 'react'
import { useAuth } from '../auth/authContext'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { MovieCard } from '../components/movies/MovieCard'
import { SectionHeading } from '../components/ui/SectionHeading'
import { Skeleton } from '../components/ui/Skeleton'
import { StatusMessage } from '../components/ui/StatusMessage'
import { ApiError, errorMessage, isAbortError } from '../services/api/client'
import type { WatchlistItem } from '../services/api/types'
import { listMyWatchlist, removeFromWatchlist } from '../services/api/watchlist'
import styles from './WatchlistPage.module.css'

type PageState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; items: WatchlistItem[] }

export function WatchlistPage() {
  const { token } = useAuth()
  const [page, setPage] = useState<PageState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0) // Increased by "Try again".
  // Films whose removal is waiting for the backend (their button is disabled).
  const [removing, setRemoving] = useState<number[]>([])
  const [feedback, setFeedback] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    listMyWatchlist(token, controller.signal)
      .then((items) => setPage({ status: 'ready', items }))
      .catch((error: unknown) => {
        if (!isAbortError(error)) setPage({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [token, attempt])

  async function handleRemove(item: WatchlistItem) {
    if (!token || removing.includes(item.movie_id)) return
    setRemoving((ids) => [...ids, item.movie_id])
    setFeedback(null)
    try {
      await removeFromWatchlist(token, item.movie_id).catch((error: unknown) => {
        // 404: already removed (e.g. in another tab), so it can leave the list too.
        if (!(error instanceof ApiError && error.status === 404)) throw error
      })
      setPage((current) =>
        current.status === 'ready'
          ? { status: 'ready', items: current.items.filter((entry) => entry.movie_id !== item.movie_id) }
          : current,
      )
      setFeedback({ tone: 'success', text: `${item.movie.display_title} was removed from your watchlist.` })
    } catch (error) {
      setFeedback({ tone: 'error', text: `${item.movie.display_title} was not removed. ${errorMessage(error)}` })
    } finally {
      setRemoving((ids) => ids.filter((id) => id !== item.movie_id))
    }
  }

  const count = page.status === 'ready' ? page.items.length : null

  return (
    <div className="container page">
      <title>Watchlist · AuraCinema</title>
      <SectionHeading
        as="h1"
        eyebrow="Saved for later"
        title="Your watchlist"
        description={
          count === null || count === 0
            ? 'Films you want to watch, kept in one place.'
            : `${count} ${count === 1 ? 'film' : 'films'} saved, newest first.`
        }
      />

      {feedback && <StatusMessage tone={feedback.tone}>{feedback.text}</StatusMessage>}

      {page.status === 'loading' && (
        <>
          <p className="visually-hidden" role="status">
            Loading your watchlist…
          </p>
          <div className={styles.list} aria-hidden="true">
            {[1, 2, 3].map((key) => (
              <div key={key} className={styles.loadingRow}>
                <Skeleton variant="poster" />
                <Skeleton width="50%" />
              </div>
            ))}
          </div>
        </>
      )}

      {page.status === 'error' && (
        <EmptyState
          title="Your watchlist could not be loaded"
          description={page.message}
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setPage({ status: 'loading' })
                setAttempt((value) => value + 1)
              }}
            >
              Try again
            </Button>
          }
        />
      )}

      {page.status === 'ready' && page.items.length === 0 && (
        <EmptyState
          title="Your watchlist is empty"
          description="Films you save from a movie's page will appear here."
          action={
            <ButtonLink to="/" variant="secondary">
              Explore the catalogue
            </ButtonLink>
          }
        />
      )}

      {page.status === 'ready' && page.items.length > 0 && (
        <ul role="list" className={styles.list}>
          {page.items.map((item) => {
            const isRemoving = removing.includes(item.movie_id)
            return (
              <li key={item.movie_id} className={styles.row}>
                <MovieCard movie={item.movie} variant="compact" />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleRemove(item)}
                  disabled={isRemoving}
                  aria-label={`Remove ${item.movie.display_title} from your watchlist`}
                >
                  {isRemoving ? 'Removing…' : 'Remove'}
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
