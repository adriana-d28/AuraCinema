// The footer shown at the bottom of every page.
//
// Its main job is legal: TMDB's API terms of use (section 3, Attribution) ask
// every application that uses the TMDB API to identify that use with the TMDB
// logo, less prominent than the application's own branding, and to show the
// notice below. Posters and movie details come from TMDB, so both are on every
// screen. The logo is TMDB's official "Alt short" file, unmodified, from
// https://www.themoviedb.org/about/logos-attribution.

import tmdbLogo from '../../assets/tmdb-logo.svg'
import { TMDB_ATTRIBUTION_NOTICE } from '../../config'
import styles from './Footer.module.css'

export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={`container ${styles.inner}`}>
        <p className={styles.brand}>
          Aura<span>Cinema</span>
        </p>
        <div className={styles.attribution}>
          <a href="https://www.themoviedb.org/" target="_blank" rel="noopener noreferrer">
            <img className={styles.tmdbLogo} src={tmdbLogo} alt="TMDB (The Movie Database)" />
          </a>
          <p className={styles.notice}>{TMDB_ATTRIBUTION_NOTICE}</p>
        </div>
      </div>
    </footer>
  )
}
