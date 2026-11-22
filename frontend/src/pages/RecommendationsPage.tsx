// Recommendations: the dedicated destination of the recommendation system
// (PLACEHOLDER with the final page structure).
//
// How it differs from Discover: Discover explores the whole catalogue; this
// page answers "what should I watch next?" for ONE signed-in user, from
// GET /api/v1/recommendations. It never shows general catalogue sections.
//
// The backend alone decides which recommender is used (collaborative
// filtering, or the popularity baseline for users without enough ratings) and
// says so in the response (source, personalized, message). The frontend will
// only DISPLAY that information; it never chooses the algorithm itself.
//
// Phase 7.1 status:
//   - The recommendation list is connected in the Recommendations phase (it
//     needs sign-in first). Until then an empty state explains this.
//   - Discovery Mode (Safe / Balanced / Adventurous) is planned but has no
//     backend support: the control is shown disabled, and changing it is not
//     possible. No request is ever sent for it.

import { ComingSoonBadge } from '../components/ui/Badge'
import { ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
import { Skeleton } from '../components/ui/Skeleton'
import styles from './RecommendationsPage.module.css'

const DISCOVERY_MODES = [
  { value: 'safe', label: 'Safe', description: 'Close to what you already enjoy' },
  { value: 'balanced', label: 'Balanced', description: 'A mix of familiar and new' },
  { value: 'adventurous', label: 'Adventurous', description: 'Further from your usual taste' },
]

export function RecommendationsPage() {
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

        {/* Discovery Mode: planned feature, shown disabled (no backend support yet). */}
        <fieldset className={styles.discoveryMode} disabled aria-describedby="discovery-mode-hint">
          <legend className={styles.modeLegend}>
            Discovery Mode <ComingSoonBadge />
          </legend>
          <div className={styles.segments}>
            {DISCOVERY_MODES.map((mode) => (
              <label key={mode.value} className={styles.segment} title={mode.description}>
                <input
                  type="radio"
                  name="discovery-mode"
                  value={mode.value}
                  defaultChecked={mode.value === 'balanced'}
                  className="visually-hidden"
                />
                <span>{mode.label}</span>
              </label>
            ))}
          </div>
          <p id="discovery-mode-hint" className={styles.modeHint}>
            Choose how adventurous your recommendations should be.
          </p>
        </fieldset>
      </div>

      {/* How the list is built: shown so users understand both situations. */}
      <Panel title="How your recommendations are chosen">
        <div className={styles.explain}>
          <div>
            <p className={styles.explainTitle}>Personalised</p>
            <p>
              Once you have rated a few films, AuraCinema compares them with films that similar viewers enjoyed and
              suggests what fits your taste.
            </p>
          </div>
          <div>
            <p className={styles.explainTitle}>Getting to know you</p>
            <p>
              Until then, you will see widely loved films as a temporary starting point. Every rating you add helps
              the list become yours.
            </p>
          </div>
        </div>
      </Panel>

      <section aria-labelledby="list-heading" className={styles.listSection}>
        <SectionHeading id="list-heading" title="Your list" />
        <EmptyState
          headingLevel="h3"
          title="Your recommendations will appear here"
          description="Recommendations need a signed-in account. Sign-in is connected in the next frontend phase."
          action={<ButtonLink to="/" variant="secondary">Explore the catalogue</ButtonLink>}
        />
        {/* Layout preview of the future list (compact cards); hidden from screen readers. */}
        <ul role="list" className={styles.preview} aria-hidden="true">
          {[1, 2, 3, 4].map((item) => (
            <li key={item} className={styles.previewCard}>
              <span className={styles.previewPoster}>
                <Skeleton variant="poster" />
              </span>
              <span className={styles.previewText}>
                <Skeleton width="70%" />
                <Skeleton width="45%" />
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
