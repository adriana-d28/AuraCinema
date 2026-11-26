// Profile: the signed-in user's own page (owner-only; it is never shown to
// other users, so it is a "Personal profile", not a public one).
//
// Data sources:
//   - identity (picture, name, email, member since, location, bio): the
//     account already loaded by AuthProvider (GET /users/me), kept up to date
//     by Settings through useAuth().updateUser, so no extra request is sent;
//   - rating metrics, genre analysis and preference summary:
//     GET /users/me/stats (counts and averages of the user's own ratings);
//   - recent ratings: GET /ratings (newest first, with the movie summary).
// Everything is edited in Settings, reached from the action at the top.

import { useEffect, useState } from 'react'
import { useAuth } from '../auth/authContext'
import { MovieCard } from '../components/movies/MovieCard'
import { RatingStars } from '../components/movies/RatingStars'
import { ProfilePicture } from '../components/profile/ProfilePicture'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
import { Skeleton } from '../components/ui/Skeleton'
import { errorMessage, isAbortError } from '../services/api/client'
import { listMyRatings } from '../services/api/ratings'
import type { GenreStatistics, Rating, UserStatistics } from '../services/api/types'
import { getMyStatistics } from '../services/api/users'
import { isVisibleGenre } from '../utils/movieFormat'
import styles from './ProfilePage.module.css'

export function ProfilePage() {
  const { user } = useAuth()

  return (
    <div className="container page">
      <title>Profile · AuraCinema</title>

      <SectionHeading
        as="h1"
        eyebrow="Personal profile"
        title="Your profile"
        description="Your film taste at a glance."
        action={
          <ButtonLink to="/settings" variant="secondary" size="sm">
            Settings
          </ButtonLink>
        }
      />

      {user && (
        <section className={styles.identity} aria-label="About you">
          <ProfilePicture />

          <dl className={styles.details}>
            <Detail label="Name" value={user.name} />
            <Detail label="Email" value={user.email} />
            <Detail label="Member since" value={formatMemberSince(user.created_at)} />
            <Detail label="Location" value={user.location} />
            <Detail label="Short bio" value={user.bio} wide />
          </dl>
        </section>
      )}

      <TasteOverview />

      {/* Connected in Phase 7.3: GET /api/v1/ratings (newest first). */}
      <RecentRatings />
    </div>
  )
}

function Detail({ label, value, wide = false }: { label: string; value: string | null; wide?: boolean }) {
  return (
    <div className={wide ? `${styles.detail} ${styles.wide}` : styles.detail}>
      <dt>{label}</dt>
      {/* An empty optional field (or the name of an account created before
          names existed) is shown as such; it can be filled in Settings. */}
      {value ? <dd className={styles.value}>{value}</dd> : <dd className={styles.pending}>Not added yet</dd>}
    </div>
  )
}

/** "November 2026" from the account's created_at timestamp. */
function formatMemberSince(isoDateTime: string): string {
  return new Date(isoDateTime).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

// ---------- Genre analysis and preference summary ----------

/** How many genres the analysis lists (the most rated ones). */
const GENRES_SHOWN = 6

/**
 * Fewest ratings a genre needs before it can be called the "highest rated"
 * (decision Q7 of the intermediate backend phase): an average of one or two
 * ratings says little about a taste.
 */
const MIN_RATINGS_FOR_HIGHEST = 3

const formatAverage = (value: number) => value.toFixed(1)
const ratingsLabel = (count: number) => (count === 1 ? '1 rating' : `${count} ratings`)

/**
 * The preference summary, built only from the statistics (no prediction).
 * The genres arrive most rated first, so the first one is the most rated.
 */
function preferenceSummary(genres: GenreStatistics[]): string[] {
  if (genres.length === 0) return []
  const mostRated = genres[0]
  const sentences = [`You rate ${mostRated.genre} films most often (${ratingsLabel(mostRated.rating_count)}).`]

  const eligible = genres.filter((genre) => genre.rating_count >= MIN_RATINGS_FOR_HIGHEST)
  if (eligible.length === 0) {
    sentences.push(
      `Rate at least ${MIN_RATINGS_FOR_HIGHEST} films of the same genre to see your highest-rated genre.`,
    )
    return sentences
  }
  // Highest average; a tie goes to the genre with more ratings (earlier in the list).
  const highest = eligible.reduce((best, genre) => (genre.average_rating > best.average_rating ? genre : best))
  const average = formatAverage(highest.average_rating)
  sentences.push(
    highest.genre === mostRated.genre
      ? `It is also your highest-rated genre, with an average of ${average} out of 5.`
      : `Your highest-rated genre is ${highest.genre}, with an average of ${average} out of 5 over ${ratingsLabel(highest.rating_count)}.`,
  )
  return sentences
}

type StatsState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; stats: UserStatistics }

function TasteOverview() {
  const { token } = useAuth()
  const [state, setState] = useState<StatsState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0) // Increased by "Try again".

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    getMyStatistics(token, controller.signal)
      .then((stats) => setState({ status: 'ready', stats }))
      .catch((error: unknown) => {
        if (!isAbortError(error)) setState({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [token, attempt])

  if (state.status === 'error') {
    return (
      <EmptyState
        headingLevel="h2"
        title="Your rating statistics could not be loaded"
        description={state.message}
        action={
          <Button
            variant="secondary"
            onClick={() => {
              setState({ status: 'loading' })
              setAttempt((value) => value + 1)
            }}
          >
            Try again
          </Button>
        }
      />
    )
  }

  const stats = state.status === 'ready' ? state.stats : null
  const hasRatings = stats !== null && stats.rating_count > 0
  // IMAX is a format, not a genre: left out of the analysis and the summary.
  // The other genres' figures do not change (a film counts in each genre).
  const genres = stats === null ? [] : stats.genres.filter(({ genre }) => isVisibleGenre(genre))

  return (
    <div className={styles.panels}>
      <Panel title="Preferred genre analysis">
        {stats === null && <LoadingLines label="Loading your rating statistics…" />}
        {stats !== null && !hasRatings && (
          <p className={styles.muted}>Rate a few films to see which genres you rate most and how highly.</p>
        )}
        {hasRatings && <GenreBars genres={genres.slice(0, GENRES_SHOWN)} />}
      </Panel>

      <Panel title="Preference summary">
        {stats === null && <LoadingLines />}
        {stats !== null && !hasRatings && (
          <>
            <p className={styles.muted}>Your summary appears after your first ratings.</p>
            <div>
              <ButtonLink to="/" variant="secondary" size="sm">
                Find a film to rate
              </ButtonLink>
            </div>
          </>
        )}
        {hasRatings && (
          <>
            <dl className={styles.metrics}>
              <div>
                <dt>Films rated</dt>
                <dd>{stats.rating_count}</dd>
              </div>
              <div>
                <dt>Average rating</dt>
                <dd>
                  {formatAverage(stats.average_rating ?? 0)}
                  <span className={styles.outOf}> / 5</span>
                </dd>
              </div>
            </dl>
            {preferenceSummary(genres).map((sentence) => (
              <p key={sentence}>{sentence}</p>
            ))}
          </>
        )}
      </Panel>
    </div>
  )
}

function GenreBars({ genres }: { genres: GenreStatistics[] }) {
  // Bar length = share of the most rated genre's count. The numbers are also
  // written as text, so the bars are only a visual aid (aria-hidden).
  const maxCount = genres[0]?.rating_count ?? 1
  return (
    <>
      <ul role="list" className={styles.genres}>
        {genres.map((genre) => (
          <li key={genre.genre}>
            <div className={styles.genreRow}>
              <span className={styles.genreName}>{genre.genre}</span>
              <span className={styles.genreFigures}>
                {ratingsLabel(genre.rating_count)} · average {formatAverage(genre.average_rating)}
              </span>
            </div>
            <span className={styles.bar} aria-hidden="true">
              <span style={{ width: `${(genre.rating_count / maxCount) * 100}%` }} />
            </span>
          </li>
        ))}
      </ul>
      <p className={styles.note}>Your most rated genres. A film counts once in each of its genres.</p>
    </>
  )
}

function LoadingLines({ label }: { label?: string }) {
  return (
    <>
      {label && (
        <p className="visually-hidden" role="status">
          {label}
        </p>
      )}
      <div className={styles.loadingLines} aria-hidden="true">
        <Skeleton width="80%" />
        <Skeleton width="60%" />
        <Skeleton width="40%" />
      </div>
    </>
  )
}

// ---------- Recent ratings (connected in Phase 7.3) ----------

/** How many of the newest ratings the profile shows. */
const RECENT_RATINGS_LIMIT = 6

type RecentState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; ratings: Rating[] }

function RecentRatings() {
  const { token } = useAuth()
  const [state, setState] = useState<RecentState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0) // Increased by "Try again".

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    listMyRatings(token, controller.signal)
      // The backend already sorts them, most recently rated first.
      .then((ratings) => setState({ status: 'ready', ratings: ratings.slice(0, RECENT_RATINGS_LIMIT) }))
      .catch((error: unknown) => {
        if (!isAbortError(error)) setState({ status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [token, attempt])

  return (
    <section aria-labelledby="recent-ratings-heading" className={styles.recent}>
      <SectionHeading id="recent-ratings-heading" title="Recent ratings" />

      {state.status === 'loading' && (
        <>
          <p className="visually-hidden" role="status">
            Loading your ratings…
          </p>
          <div className={styles.recentList} aria-hidden="true">
            {[1, 2, 3].map((key) => (
              <div key={key} className={styles.recentLoading}>
                <Skeleton variant="poster" />
                <Skeleton width="50%" />
              </div>
            ))}
          </div>
        </>
      )}

      {state.status === 'error' && (
        <EmptyState
          headingLevel="h3"
          title="Your ratings could not be loaded"
          description={state.message}
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setState({ status: 'loading' })
                setAttempt((value) => value + 1)
              }}
            >
              Try again
            </Button>
          }
        />
      )}

      {state.status === 'ready' && state.ratings.length === 0 && (
        <EmptyState
          headingLevel="h3"
          title="No ratings to show yet"
          description="The films you rate will appear here, newest first."
          action={
            <ButtonLink to="/" variant="secondary">
              Find a film to rate
            </ButtonLink>
          }
        />
      )}

      {state.status === 'ready' && state.ratings.length > 0 && (
        <ul role="list" className={styles.recentList}>
          {state.ratings.map((rating) => (
            <li key={rating.movie_id}>
              <MovieCard movie={rating.movie} variant="compact" extra={<RatingStars value={rating.rating} />} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
