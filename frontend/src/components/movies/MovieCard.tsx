// A clickable movie card that opens the movie's details page.
//
// Two variants, for two different jobs:
//   - "standard": poster on top, title and metadata below. Used in grids where
//     the poster is the visual anchor (the Discover catalogue).
//   - "compact": small poster on the left, text on the right. Used in lists
//     where the information matters more than the image (recommendations,
//     watchlist, recent ratings), so posters do not become too large there.
//
// The whole card is one link, so it is a single stop for keyboard users. The
// poster's alt text is empty because the title is already written in the card.
//
// The card only needs a few fields, which every movie type returned by the
// API provides (MovieSummary in lists, MovieDetails, RecommendedMovie...). The
// readable title and the year come ready-made from the backend.

import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { MovieSummary } from '../../services/api/types'
import { MoviePoster } from './MoviePoster'
import styles from './MovieCard.module.css'
import { visibleGenres } from '../../utils/movieFormat'

export type MovieCardData = Pick<MovieSummary, 'movie_id' | 'display_title' | 'year' | 'genres' | 'poster_url'>

interface MovieCardProps {
  movie: MovieCardData
  variant?: 'standard' | 'compact'
  /** Optional extra line, e.g. "Recommendation #1" in a later phase. */
  extra?: ReactNode
}

export function MovieCard({ movie, variant = 'standard', extra }: MovieCardProps) {
  const { display_title: title, year } = movie
  // Show at most two genres, so the metadata line stays short (IMAX is not shown).
  const genres = visibleGenres(movie.genres).slice(0, 2).join(', ')
  const metadata = [year, genres].filter(Boolean).join(' · ')

  return (
    <article className={`${styles.card} ${styles[variant]}`}>
      <Link to={`/movies/${movie.movie_id}`} className={styles.link}>
        <MoviePoster posterUrl={movie.poster_url} title={title} alt="" className={styles.poster} />
        <div className={styles.body}>
          <h3 className={styles.title}>{title}</h3>
          {metadata && <p className={styles.meta}>{metadata}</p>}
          {extra && <div className={styles.extra}>{extra}</div>}
        </div>
      </Link>
    </article>
  )
}
