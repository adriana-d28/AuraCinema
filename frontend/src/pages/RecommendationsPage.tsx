// Recommendations: the dedicated destination of the recommendation system.
//
// How it differs from Discover: Discover explores the whole catalogue; this
// page answers "what should I watch next?" for ONE signed-in user, from
// GET /api/v1/recommendations. It never shows general catalogue sections.
//
// The backend alone decides which recommender is used (collaborative
// filtering, or the popularity baseline for users without enough ratings) and
// says so in the response (source, personalized, message). The frontend only
// DISPLAYS that information; it never chooses the algorithm itself.
//
// Discovery Mode (Phase 7.4) is a separate, optional feature, OFF by default:
// the page first shows the plain personalised list (the model's own order).
// A switch turns it on (Balanced first); Safe / Balanced / Adventurous then
// re-rank the personalised list on the backend (ml/src/discovery_mode.py), and
// turning it off returns to the plain list. The state lives in the address
// (/recommendations?mode=adventurous; no "mode" = off), like the Discover
// filters, so going back from a movie's page keeps it; it is not stored in the
// account. While the list comes from the popularity baseline the switch is
// disabled, because there is no personal taste to explore from.
//
// Rating a film or saving it to the watchlist happens on the movie's page; the
// list is requested again when the user comes back, so it reflects new ratings.

import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useAuth } from '../auth/authContext'
import { MovieCard } from '../components/movies/MovieCard'
import { Badge } from '../components/ui/Badge'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
import { Skeleton } from '../components/ui/Skeleton'
import { ApiError, errorMessage, isAbortError } from '../services/api/client'
import { getMyRecommendations } from '../services/api/recommendations'
import type { DiscoveryMode, RecommendationResponse } from '../services/api/types'
import styles from './RecommendationsPage.module.css'

const DISCOVERY_MODES: { value: DiscoveryMode; label: string; description: string }[] = [
  { value: 'safe', label: 'Safe', description: 'Close to what you already enjoy.' },
  { value: 'balanced', label: 'Balanced', description: 'A mix of familiar favourites and new directions.' },
  { value: 'adventurous', label: 'Adventurous', description: 'Lesser-known films and genres beyond your usual taste.' },
]
/** The mode selected when Discovery Mode is turned on. */
const DEFAULT_MODE: DiscoveryMode = 'balanced'

/** The mode from the address; null (Discovery Mode off) when absent or unknown. */
function readMode(value: string | null): DiscoveryMode | null {
  return DISCOVERY_MODES.some((mode) => mode.value === value) ? (value as DiscoveryMode) : null
}

// As on Discover, each result remembers which request (`key`) it answers, so a
// new mode shows "loading" until its own answer arrives.
type ListResult =
  | { key: string; status: 'error'; unavailable: boolean; message: string }
  | { key: string; status: 'ready'; data: RecommendationResponse }
type ListState = { status: 'loading' } | ListResult

export function RecommendationsPage() {
  const { token } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const mode = readMode(searchParams.get('mode'))
  const [result, setResult] = useState<ListResult | null>(null)
  const [attempt, setAttempt] = useState(0) // Increased by "Try again".
  const requestKey = JSON.stringify([mode, attempt])
  const list: ListState = result?.key === requestKey ? result : { status: 'loading' }
  // Last known answer to "is the list personalised?", kept while a new mode loads.
  const personalized = result?.status === 'ready' ? result.data.personalized : null

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    getMyRecommendations(token, mode, controller.signal)
      .then((data) => setResult({ key: requestKey, status: 'ready', data }))
      .catch((error: unknown) => {
        if (isAbortError(error)) return
        const unavailable = error instanceof ApiError && error.status === 503
        setResult({ key: requestKey, status: 'error', unavailable, message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [token, mode, requestKey])

  const selected = DISCOVERY_MODES.find((option) => option.value === mode)
  const modeDisabled = personalized === false
  const discoveryOn = mode !== null && !modeDisabled

  function setMode(next: DiscoveryMode | null) {
    setSearchParams(next ? { mode: next } : {}, { replace: true })
  }

  let hint = 'Off: your list follows your taste as closely as possible. Turn it on to explore beyond it.'
  if (modeDisabled) hint = 'Available once your recommendations are personalised.'
  else if (selected) hint = selected.description

  return (
    <div className="container page">
      <title>Recommendations · AuraCinema</title>

      <div className={styles.top}>
        <SectionHeading
          as="h1"
          eyebrow="Personalised for you"
          title="Your recommendations"
          description="Films chosen by AuraCinema's recommendation system from the ratings you give."
        />

        <div className={styles.discoveryMode}>
          <div className={styles.modeHeader}>
            <span id="discovery-mode-label" className={styles.modeLegend}>
              Discovery Mode
            </span>
            {/* A switch: its name is "Discovery Mode", its state is aria-checked. */}
            <button
              type="button"
              role="switch"
              aria-checked={discoveryOn}
              aria-labelledby="discovery-mode-label"
              aria-describedby="discovery-mode-hint"
              disabled={modeDisabled}
              className={styles.switch}
              onClick={() => setMode(discoveryOn ? null : DEFAULT_MODE)}
            >
              <span className={styles.switchTrack} aria-hidden="true">
                <span className={styles.switchThumb} />
              </span>
              <span aria-hidden="true">{discoveryOn ? 'On' : 'Off'}</span>
            </button>
          </div>

          {discoveryOn && (
            <fieldset className={styles.modeOptions}>
              <legend className="visually-hidden">How adventurous</legend>
              <div className={styles.segments}>
                {DISCOVERY_MODES.map((option) => (
                  <label key={option.value} className={styles.segment}>
                    <input
                      type="radio"
                      name="discovery-mode"
                      value={option.value}
                      checked={option.value === mode}
                      onChange={() => setMode(option.value)}
                      className="visually-hidden"
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          <p id="discovery-mode-hint" className={styles.modeHint}>
            {hint}
          </p>
        </div>
      </div>

      <Panel title="How your recommendations are chosen">
        <div className={styles.explain}>
          <div>
            <p className={styles.explainTitle}>Personalised</p>
            <p>
              Once you have rated a few films, AuraCinema compares them with films that similar viewers enjoyed and
              suggests what fits your taste. Turn on Discovery Mode to decide how far the list may wander: Safe
              stays close to your taste, Adventurous mixes in lesser-known films and other genres.
            </p>
          </div>
          <div>
            <p className={styles.explainTitle}>Getting to know you</p>
            <p>
              Until then, you will see widely loved films as a temporary starting point. Rate at least two films,
              giving them different scores, and the list becomes yours.
            </p>
          </div>
        </div>
      </Panel>

      <section aria-labelledby="list-heading" className={styles.listSection}>
        <SectionHeading
          id="list-heading"
          title="Your list"
          action={list.status === 'ready' && <ListBadge data={list.data} />}
        />

        {list.status === 'loading' && (
          <>
            <p className="visually-hidden" role="status">
              Loading your recommendations…
            </p>
            <ul role="list" className={styles.list} aria-hidden="true">
              {[1, 2, 3, 4].map((item) => (
                <li key={item} className={styles.loadingCard}>
                  <Skeleton variant="poster" />
                  <span className={styles.loadingText}>
                    <Skeleton width="70%" />
                    <Skeleton width="45%" />
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}

        {list.status === 'error' && (
          <EmptyState
            headingLevel="h3"
            title={
              list.unavailable ? 'Recommendations are temporarily unavailable' : 'Your recommendations could not be loaded'
            }
            description={
              list.unavailable
                ? 'The recommendation service is not available right now. Please try again in a moment.'
                : list.message
            }
            action={
              <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>
                Try again
              </Button>
            }
          />
        )}

        {list.status === 'ready' && !list.data.personalized && (
          <div className={styles.coldStart} role="status">
            <p className={styles.coldStartTitle}>{list.data.message}</p>
            <p>
              These are popular films, not yet chosen for you. Rate at least two films, with different scores, to
              get personalised recommendations and unlock Discovery Mode.
            </p>
          </div>
        )}

        {list.status === 'ready' && list.data.items.length === 0 && (
          <EmptyState
            headingLevel="h3"
            title="No recommendations right now"
            description="There are no films left to suggest from your ratings. Explore the catalogue and rate a few different films."
            action={
              <ButtonLink to="/" variant="secondary">
                Explore the catalogue
              </ButtonLink>
            }
          />
        )}

        {list.status === 'ready' && list.data.items.length > 0 && (
          <ol className={styles.list} aria-label="Recommended films, best first">
            {list.data.items.map((movie) => (
              <li key={movie.movie_id}>
                <MovieCard movie={movie} variant="compact" extra={<span className={styles.rank}>#{movie.rank}</span>} />
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  )
}

/** Says, next to the heading, how the list shown was produced. */
function ListBadge({ data }: { data: RecommendationResponse }) {
  if (!data.personalized) return <Badge>Popular picks</Badge>
  const label = DISCOVERY_MODES.find((option) => option.value === data.discovery_mode)?.label
  return <Badge tone="accent">{label ? `Personalised · ${label}` : 'Personalised'}</Badge>
}
