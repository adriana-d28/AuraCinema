// A large, cinematic presentation of ONE movie, built only from its poster.
//
// TMDB "backdrop" (wide) images are not stored by the backend, so this
// component creates the atmosphere from the portrait poster it already has:
//   layer 1 (back):   the SAME poster, enlarged and heavily blurred, so only
//                     its colours remain - a soft glow in the film's palette;
//   layer 2:          dark gradients on top, so the text is always readable
//                     and the edges melt into the page background;
//   layer 3 (front):  the sharp poster, the title, metadata and actions.
// Everything is plain CSS (blur, gradients). No extra images or requests.
//
// Used by the Discover featured area (headingLevel "h2") and by the movie
// details page (headingLevel "h1"). Any extra content, such as
// buttons, is passed as children.

import type { CSSProperties, ReactNode } from 'react'
import type { MovieDetails } from '../../services/api/types'
import { formatRuntime } from '../../utils/movieFormat'
import { MoviePoster } from './MoviePoster'
import styles from './MovieHero.module.css'

interface MovieHeroProps {
  movie: MovieDetails
  /** Small label above the title, e.g. "Featured from the catalogue". */
  eyebrow?: ReactNode
  headingLevel?: 'h1' | 'h2'
  /** Show the plot summary (shortened to a few lines). */
  showOverview?: boolean
  children?: ReactNode
}

export function MovieHero({ movie, eyebrow, headingLevel = 'h2', showOverview = true, children }: MovieHeroProps) {
  const Heading = headingLevel
  const { display_title: title, year } = movie
  const metadata = [year, movie.runtime ? formatRuntime(movie.runtime) : null, movie.genres.join(', ')]
    .filter(Boolean)
    .join(' · ')

  // The poster address is handed to CSS as a variable (--hero-image), so the
  // stylesheet can use it for the blurred background layer.
  const backdropStyle = movie.poster_url
    ? ({ '--hero-image': `url("${movie.poster_url}")` } as CSSProperties)
    : undefined

  return (
    <section className={styles.hero} aria-labelledby={`hero-title-${movie.movie_id}`}>
      {/* Decorative background layers: hidden from screen readers. */}
      <div className={styles.backdrop} style={backdropStyle} aria-hidden="true" />
      <div className={styles.shade} aria-hidden="true" />

      <div className={`container ${styles.content}`}>
        <MoviePoster
          posterUrl={movie.poster_url}
          title={title}
          alt={`Poster of ${title}`}
          loading="eager"
          className={styles.poster}
        />
        <div className={styles.text}>
          {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
          <Heading id={`hero-title-${movie.movie_id}`} className={styles.title}>
            {title}
          </Heading>
          {metadata && <p className={styles.meta}>{metadata}</p>}
          {showOverview && movie.overview && <p className={styles.overview}>{movie.overview}</p>}
          {children && <div className={styles.actions}>{children}</div>}
        </div>
      </div>
    </section>
  )
}
