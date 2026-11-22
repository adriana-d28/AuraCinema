// The footer shown at the bottom of every page.
//
// Its main job is legal: TMDB's terms ask every application that uses the
// TMDB API to show the notice below word for word. Posters and movie details
// come from TMDB, so the notice is on every screen.
// Decision for this iteration: the text notice only, no Credits/About page.
// Whether the TMDB logo is also required must be reviewed against TMDB's
// current rules (see the UI/UX specification, section 17).

import { TMDB_ATTRIBUTION_NOTICE } from '../../config'
import styles from './Footer.module.css'

export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={`container ${styles.inner}`}>
        <p className={styles.brand}>
          Aura<span>Cinema</span>
        </p>
        <p className={styles.notice}>{TMDB_ATTRIBUTION_NOTICE}</p>
      </div>
    </footer>
  )
}
