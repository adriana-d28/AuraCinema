// Profile: who the user is and what kind of films they like (PLACEHOLDER).
//
// The structure follows the original profile wireframe. Each element is in
// one of three situations, written next to it in the code:
//   [later frontend phase] the API supports it, but sign-in is needed first
//                          (email, "member since", recent ratings);
//   [needs backend]        the API has no data for it yet (picture, name,
//                          location, bio, genre analysis, preference summary).
//                          These are shown DISABLED with "Coming soon"; the
//                          intermediate backend phase will add them.
// The Settings link works: Settings is reached from here, not from the main menu.

import { ComingSoonBadge } from '../components/ui/Badge'
import { ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
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

      {/* [later frontend phase] Recent ratings: GET /api/v1/ratings exists (sign-in needed). */}
      <section aria-labelledby="recent-ratings-heading" className={styles.recent}>
        <SectionHeading id="recent-ratings-heading" title="Recent ratings" />
        <EmptyState
          headingLevel="h3"
          title="No ratings to show yet"
          description="The films you rate will appear here, newest first. Rating is connected in a later phase."
        />
      </section>
    </div>
  )
}
