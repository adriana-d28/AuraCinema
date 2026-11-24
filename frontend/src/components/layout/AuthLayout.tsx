// The frame for the Register and Log in pages.
//
// Following the original registration wireframe, the screen has two parts:
//   - a visual side that introduces AuraCinema (left on wide screens);
//   - the form side, where React Router places the page (<Outlet />).
//
// The visual side reuses three real catalogue posters (Twelve Monkeys, Heat
// and The City of Lost Children, as stored by the backend) as a small,
// overlapping "film archive" composition, on top of the
// same blurred-poster technique used by the movie hero. No extra image files
// or image sources are needed. On phones the visual side shrinks to a short
// band with the wordmark, so the form is reached immediately.

import { Link, Outlet, ScrollRestoration } from 'react-router'
import { TMDB_ATTRIBUTION_NOTICE } from '../../config'
import styles from './AuthLayout.module.css'

// Three fixed poster addresses for the composition. They are the poster_url
// values the backend stores for movies 32, 6 and 29. The page is shown before
// sign-in, so it does not load them from the API.
const collagePosters = [
  'https://image.tmdb.org/t/p/w500/gt3iyguaCIw8DpQZI1LIN5TohM2.jpg',
  'https://image.tmdb.org/t/p/w500/umSVjVdbVwtx5ryCA2QXL44Durm.jpg',
  'https://image.tmdb.org/t/p/w500/zwTqStZ0wCDoi5hD1wZjJjUKtFq.jpg',
]

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
