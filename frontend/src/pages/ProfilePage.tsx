// Profile: who the user is and what kind of films they like (PLACEHOLDER).
//
// The structure follows the original profile wireframe. Each element is in
// one of three situations, written next to it in the code:
//   [later frontend phase] the API supports it, but sign-in is needed first
//                          (email, "member since");
//   [needs backend]        the API has no data for it yet (picture, name,
//                          location, bio, genre analysis, preference summary).
//                          These are shown DISABLED with "Coming soon"; the
//                          intermediate backend phase will add them.
// The Settings link works: Settings is reached from here, not from the main menu.
//
// Recent ratings are CONNECTED (added at the end of Phase 7.3): GET /ratings
// returns the user's ratings newest first, each with its movie summary, so
// one request is enough. The newest RECENT_RATINGS_LIMIT are shown.

import { useEffect, useState } from 'react'
import { useAuth } from '../auth/authContext'
import { MovieCard } from '../components/movies/MovieCard'
import { RatingStars } from '../components/movies/RatingStars'
import { ComingSoonBadge } from '../components/ui/Badge'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
import { Skeleton } from '../components/ui/Skeleton'
import { errorMessage, isAbortError } from '../services/api/client'
import { listMyRatings } from '../services/api/ratings'
import type { Rating } from '../services/api/types'
import styles from './ProfilePage.module.css'

export function ProfilePage() {
  return (
    <div className="container page">
      <title>Profile · AuraCinema</title>

      <SectionHeading
        as="h1"
        eyebrow="Public profile"
        title="Your profile"
        description="Your film taste at a glance."
        action={
          <ButtonLink to="/settings" variant="secondary" size="sm">
            Settings
          </ButtonLink>
        }
      />

      <section className={styles.identity} aria-label="About you">
        {/* [needs backend] Profile picture. */}
        <div className={styles.avatarWrap}>
          <div className={styles.avatar} aria-hidden="true">
            <svg viewBox="0 0 48 48" focusable="false">
              <circle cx="24" cy="18" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <path d="M9 41c2.5-8 8.5-12 15-12s12.5 4 15 12" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </div>
          <span className={styles.avatarLabel}>
            Profile picture <ComingSoonBadge />
          </span>
        </div>

        <dl className={styles.details}>
          {/* [needs backend] Name: accounts only have an email and a password today. */}
          <div className={styles.detail}>
            <dt>Name</dt>
            <dd className={styles.planned}>
              Not available yet <ComingSoonBadge />
            </dd>
          </div>
          {/* [later frontend phase] Email and creation date come from GET /api/v1/users/me. */}
          <div className={styles.detail}>
            <dt>Email</dt>
            <dd className={styles.pending}>Shown after sign-in</dd>
          </div>
          <div className={styles.detail}>
            <dt>Member since</dt>
            <dd className={styles.pending}>Shown after sign-in</dd>
          </div>
          {/* [needs backend] Location and bio. */}
          <div className={styles.detail}>
            <dt>Location</dt>
            <dd className={styles.planned}>
              Not available yet <ComingSoonBadge />
            </dd>
          </div>
          <div className={`${styles.detail} ${styles.wide}`}>
            <dt>Short bio</dt>
            <dd className={styles.planned}>
              Not available yet <ComingSoonBadge />
            </dd>
          </div>
        </dl>
      </section>

      <div className={styles.panels}>
        {/* [needs backend] Genre analysis and preference summary: no endpoint yet. */}
        <Panel title="Preferred genre analysis" comingSoon>
          <p>The genres you rate most and how highly you rate them.</p>
          <div className={styles.bars} aria-hidden="true">
            <span style={{ width: '82%' }} />
            <span style={{ width: '64%' }} />
            <span style={{ width: '45%' }} />
            <span style={{ width: '30%' }} />
          </div>
        </Panel>
        <Panel title="Preference summary" comingSoon>
          <p>A short description of your taste, based on your ratings.</p>
        </Panel>
      </div>

      {/* Connected: GET /api/v1/ratings (newest first). */}
      <RecentRatings />
    </div>
  )
}

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
