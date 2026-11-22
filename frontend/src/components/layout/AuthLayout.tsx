// The frame for the Register and Log in pages.
//
// Following the original registration wireframe, the screen has two parts:
//   - a visual side that introduces AuraCinema (left on wide screens);
//   - the form side, where React Router places the page (<Outlet />).
//
// The visual side reuses three real catalogue posters (from the demonstration
// data) as a small, overlapping "film archive" composition, on top of the
// same blurred-poster technique used by the movie hero. No extra image files
// or image sources are needed. On phones the visual side shrinks to a short
// band with the wordmark, so the form is reached immediately.

import { Link, Outlet, ScrollRestoration } from 'react-router'
import { TMDB_ATTRIBUTION_NOTICE } from '../../config'
import { demoCatalogueMovies, demoFeaturedMovie } from '../../data/demoMovies'
import styles from './AuthLayout.module.css'

// Three posters for the composition (demonstration data, see demoMovies.ts).
const collagePosters = [demoCatalogueMovies[0], demoFeaturedMovie, demoCatalogueMovies[2]]
  .map((movie) => movie.poster_url)
  .filter((url): url is string => url !== null)

export function AuthLayout() {
  return (
    <div className={styles.shell}>
      <aside className={styles.visual}>
        {/* Blurred colour glow taken from the middle poster. */}
        <div
          className={styles.glow}
          style={{ backgroundImage: `url("${collagePosters[1]}")` }}
          aria-hidden="true"
        />
        <Link to="/" className={styles.brand} aria-label="AuraCinema, go to Discover">
          Aura<span>Cinema</span>
        </Link>
        {/* Decorative posters: alt="" so screen readers skip them. */}
        <div className={styles.collage} aria-hidden="true">
          {collagePosters.map((url) => (
            <img key={url} src={url} alt="" className={styles.collagePoster} />
          ))}
        </div>
        <div className={styles.intro}>
          <p className={styles.eyebrow}>Movie discovery</p>
          <p className={styles.tagline}>Find the films that stay with you.</p>
          <p className={styles.lead}>
            Rate what you have watched, and AuraCinema learns your taste to recommend what to watch next.
          </p>
        </div>
      </aside>

      <main className={styles.formSide}>
        <div className={styles.formInner}>
          <Outlet />
        </div>
        <p className={styles.notice}>{TMDB_ATTRIBUTION_NOTICE}</p>
      </main>
      <ScrollRestoration />
    </div>
  )
}
