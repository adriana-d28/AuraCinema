// Movie details: one film, its information, and the user's two actions.
//
// The address is /movies/:movieId (for example /movies/6). Three requests are
// sent together when the page opens:
//   - GET /movies/{id}/details  the film (public; 404 = not in the catalogue);
//   - GET /ratings              the user's ratings, to find this film's rating;
//   - GET /watchlist            the user's watchlist, to know if the film is in it.
// The backend has no "one rating" / "one watchlist entry" endpoint, so the
// page looks the film up in the user's own lists.
//
// As in the original wireframe, "Add to watchlist" and "Rate this film" are two
// separate actions in two separate places. They are also INDEPENDENT: saving a
// rating never changes the watchlist and the other way round (a project
// decision; watchlist films also stay eligible for recommendations).
// The page only changes what it shows after the backend has confirmed an action.

import { useEffect, useState } from 'react'
import { useParams } from 'react-router'
import { useAuth } from '../auth/authContext'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { MovieHero } from '../components/movies/MovieHero'
import { Panel } from '../components/ui/Panel'
import { RatingInput } from '../components/movies/RatingInput'
import { Skeleton } from '../components/ui/Skeleton'
import { StatusMessage } from '../components/ui/StatusMessage'
import { ApiError, errorMessage, isAbortError } from '../services/api/client'
import { getMovieDetails } from '../services/api/movies'
import { deleteRating, listMyRatings, saveRating } from '../services/api/ratings'
import type { MovieDetails } from '../services/api/types'
import { addToWatchlist, listMyWatchlist, removeFromWatchlist } from '../services/api/watchlist'
import { formatRuntime } from '../utils/movieFormat'
import styles from './MovieDetailsPage.module.css'

type PageState =
  | { status: 'loading' }
  | { status: 'not_found' }
  | { status: 'error'; message: string }
  | { status: 'ready'; movie: MovieDetails }

interface Feedback {
  tone: 'success' | 'error'
  text: string
}

/** The movie ID from the address, or null when it is not a positive whole number. */
function parseMovieId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null
  const id = Number(value)
  return id > 0 && Number.isSafeInteger(id) ? id : null
}

export function MovieDetailsPage() {
  // useParams reads the ":movieId" part of the address as text.
  const movieId = parseMovieId(useParams().movieId)
  if (movieId === null) return <MovieMessage notFound />
  // key: opening another film starts with fresh state (no old rating or message).
  return <MovieDetailsContent key={movieId} movieId={movieId} />
}

function MovieDetailsContent({ movieId }: { movieId: number }) {
  const { token } = useAuth()

  const [page, setPage] = useState<PageState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0) // Increased by "Try again".

  // Rating: the value saved in the backend, and the stars currently chosen.
  const [savedRating, setSavedRating] = useState<number | null>(null)
  const [chosenRating, setChosenRating] = useState<number | null>(null)
  const [ratingPending, setRatingPending] = useState(false)
  const [ratingFeedback, setRatingFeedback] = useState<Feedback | null>(null)

  // Watchlist: whether the film is saved, as confirmed by the backend.
  const [inWatchlist, setInWatchlist] = useState(false)
  const [watchlistPending, setWatchlistPending] = useState(false)
  const [watchlistFeedback, setWatchlistFeedback] = useState<Feedback | null>(null)

  useEffect(() => {
    if (!token) return // Not reached: the page is only shown to signed-in users.
    const controller = new AbortController()
    Promise.all([
      getMovieDetails(movieId, controller.signal),
      listMyRatings(token, controller.signal),
      listMyWatchlist(token, controller.signal),
    ])
      .then(([movie, ratings, watchlist]) => {
        const rating = ratings.find((item) => item.movie_id === movieId)?.rating ?? null
        setSavedRating(rating)
        setChosenRating(rating)
        setInWatchlist(watchlist.some((item) => item.movie_id === movieId))
        setPage({ status: 'ready', movie })
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        if (error instanceof ApiError && error.status === 404) setPage({ status: 'not_found' })
        else setPage({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [movieId, token, attempt])

  async function handleSaveRating() {
    // Nothing chosen, nothing changed, or a request already running: no request.
    if (!token || chosenRating === null || chosenRating === savedRating || ratingPending) return
    const isUpdate = savedRating !== null
    setRatingPending(true)
    setRatingFeedback(null)
    try {
      // PUT creates the rating or replaces the existing one.
      const saved = await saveRating(token, movieId, chosenRating)
      setSavedRating(saved.rating)
      setChosenRating(saved.rating)
      setRatingFeedback({
        tone: 'success',
        text: `${isUpdate ? 'Rating updated' : 'Rating saved'}: ${saved.rating} out of 5.`,
      })
    } catch (error) {
      setRatingFeedback({ tone: 'error', text: `Your rating was not saved. ${errorMessage(error)}` })
    } finally {
      setRatingPending(false)
    }
  }

  async function handleRemoveRating() {
    if (!token || savedRating === null || ratingPending) return
    setRatingPending(true)
    setRatingFeedback(null)
    try {
      await deleteRating(token, movieId)
      setSavedRating(null)
      setChosenRating(null)
      setRatingFeedback({ tone: 'success', text: 'Rating removed.' })
    } catch (error) {
      // 404: the rating was already gone (e.g. removed in another tab).
      if (error instanceof ApiError && error.status === 404) {
        setSavedRating(null)
        setChosenRating(null)
        setRatingFeedback({ tone: 'success', text: 'Rating removed.' })
      } else {
        setRatingFeedback({ tone: 'error', text: `Your rating was not removed. ${errorMessage(error)}` })
      }
    } finally {
      setRatingPending(false)
    }
  }

  async function handleToggleWatchlist() {
    if (!token || watchlistPending) return
    setWatchlistPending(true)
    setWatchlistFeedback(null)
    try {
      if (inWatchlist) {
        await removeFromWatchlist(token, movieId).catch((error: unknown) => {
          // 404: it was not in the watchlist any more, which is the goal anyway.
          if (!(error instanceof ApiError && error.status === 404)) throw error
        })
        setInWatchlist(false)
        setWatchlistFeedback({ tone: 'success', text: 'Removed from your watchlist.' })
      } else {
        // PUT is idempotent: the film can never be added twice.
        await addToWatchlist(token, movieId)
        setInWatchlist(true)
        setWatchlistFeedback({ tone: 'success', text: 'Added to your watchlist.' })
      }
    } catch (error) {
      setWatchlistFeedback({ tone: 'error', text: `The watchlist was not changed. ${errorMessage(error)}` })
    } finally {
      setWatchlistPending(false)
    }
  }

  if (page.status === 'loading') {
    return (
      <div className="container page">
        <title>Movie details · AuraCinema</title>
        <h1 className="visually-hidden">Movie details</h1>
        <p className="visually-hidden" role="status">
          Loading the film…
        </p>
        <div className={styles.loadingPreview} aria-hidden="true">
          <Skeleton variant="poster" />
          <div className={styles.loadingText}>
            <Skeleton width="60%" />
            <Skeleton width="35%" />
            <Skeleton width="90%" />
          </div>
        </div>
      </div>
    )
  }

  if (page.status === 'not_found') return <MovieMessage notFound />
  if (page.status === 'error') {
    return (
      <MovieMessage
        errorText={page.message}
        onRetry={() => {
          setPage({ status: 'loading' })
          setAttempt((value) => value + 1)
        }}
      />
    )
  }

  const { movie } = page
  const title = movie.display_title
  // FR-4: when TMDB details are missing, show the catalogue data calmly, without an error.
  const hasExtraDetails = movie.metadata_status === 'available'
  const facts = [
    { label: 'Release date', value: movie.release_date && formatDate(movie.release_date) },
    { label: 'Runtime', value: movie.runtime && formatRuntime(movie.runtime) },
    { label: 'Genres', value: movie.genres.join(', ') },
  ].filter((fact) => fact.value)

  return (
    <>
      <title>{`${title} · AuraCinema`}</title>
      {/* The full plot is shown below, so the hero keeps a balanced height. */}
      <MovieHero movie={movie} headingLevel="h1" eyebrow="Movie details" showOverview={false}>
        <Button
          variant={inWatchlist ? 'secondary' : 'primary'}
          onClick={handleToggleWatchlist}
          disabled={watchlistPending}
        >
          {watchlistPending ? 'Saving…' : inWatchlist ? 'Remove from watchlist' : 'Add to watchlist'}
        </Button>
        {inWatchlist && <span className={styles.savedLabel}>In your watchlist</span>}
        {watchlistFeedback && <StatusMessage tone={watchlistFeedback.tone}>{watchlistFeedback.text}</StatusMessage>}
      </MovieHero>

      <div className={`container ${styles.body}`}>
        <section aria-labelledby="about-heading" className={styles.about}>
          <h2 id="about-heading" className={styles.aboutTitle}>
            About this film
          </h2>
          {movie.overview ? (
            <p className={styles.overview}>{movie.overview}</p>
          ) : (
            <p className={styles.missingNote}>
              {hasExtraDetails
                ? 'No plot summary is available for this film.'
                : 'More information about this film, such as its poster and plot, is not available yet.'}
            </p>
          )}
          {facts.length > 0 && (
            <dl className={styles.facts}>
              {facts.map((fact) => (
                <div key={fact.label} className={styles.fact}>
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <Panel title="Rate this film" className={styles.ratePanel}>
          <p className={styles.currentRating}>
            {savedRating === null ? 'You have not rated this film yet.' : `Your rating: ${savedRating} out of 5.`}
          </p>
          <RatingInput
            label={`Your rating for ${title}`}
            value={chosenRating}
            onChange={setChosenRating}
            disabled={ratingPending}
          />
          <p className={styles.hint}>
            Rate from half a star to five stars. Your ratings shape your recommendations.
          </p>
          <div className={styles.ratingActions}>
            <Button
              onClick={handleSaveRating}
              disabled={ratingPending || chosenRating === null || chosenRating === savedRating}
            >
              {ratingPending ? 'Saving…' : savedRating === null ? 'Save rating' : 'Update rating'}
            </Button>
            {savedRating !== null && (
              <Button variant="ghost" onClick={handleRemoveRating} disabled={ratingPending}>
                Remove rating
              </Button>
            )}
          </div>
          {ratingFeedback && <StatusMessage tone={ratingFeedback.tone}>{ratingFeedback.text}</StatusMessage>}
        </Panel>
      </div>
    </>
  )
}

interface MovieMessageProps {
  notFound?: boolean
  errorText?: string
  onRetry?: () => void
}

/** The "not found" page, or a loading error with "Try again". */
function MovieMessage({ notFound = false, errorText, onRetry }: MovieMessageProps) {
  return (
    <div className="container page">
      <title>Movie details · AuraCinema</title>
      <h1 className="visually-hidden">Movie details</h1>
      <EmptyState
        title={notFound ? 'Film not found' : 'This film could not be loaded'}
        description={notFound ? 'There is no film with this address in the AuraCinema catalogue.' : errorText}
        action={
          notFound ? (
            <ButtonLink to="/" variant="secondary">
              Back to Discover
            </ButtonLink>
          ) : (
            <Button variant="secondary" onClick={onRetry}>
              Try again
            </Button>
          )
        }
      />
    </div>
  )
}

/** "1995-12-15" -> "15 December 1995" (read as a calendar date, not a time). */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}
