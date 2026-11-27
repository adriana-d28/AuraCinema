// The MovieLens community rating of a movie: the mean of its MovieLens ratings
// (0.5-5.0) and how many ratings that mean is based on. It comes from the
// backend (movielens_average_rating / movielens_rating_count) and does NOT
// include AuraCinema users' ratings.
//
// It is drawn differently from the user's own rating (RatingStars, burgundy
// stars): one gold star, the number and the "MovieLens" label, so the two
// are never confused. Screen readers get the full sentence instead.
//
// Two variants:
//   - "short": "★ 4.4 MovieLens", for movie cards;
//   - "full":  "★ 4.4 / 5 · MovieLens average of 95,088 ratings", for the hero.

import { formatAverageRating, formatCount } from '../../utils/movieFormat'
import { STAR_PATH } from './RatingStars'
import styles from './CommunityRating.module.css'

interface CommunityRatingProps {
  average: number | null
  count: number | null
  variant?: 'short' | 'full'
}

export function CommunityRating({ average, count, variant = 'short' }: CommunityRatingProps) {
  // Nothing is shown until the backend has the value (never an invented number).
  if (average === null || count === null) return null
  const value = formatAverageRating(average)
  const ratings = `${formatCount(count)} ${count === 1 ? 'rating' : 'ratings'}`

  return (
    <span className={`${styles.rating} ${styles[variant]}`}>
      <svg viewBox="0 0 24 24" className={styles.star} aria-hidden="true" focusable="false">
        <path d={STAR_PATH} />
      </svg>
      <span aria-hidden="true">
        {variant === 'full' ? (
          <>
            <span className={styles.value}>{value}</span> / 5 · MovieLens average of {ratings}
          </>
        ) : (
          <>
            <span className={styles.value}>{value}</span> <span className={styles.label}>MovieLens</span>
          </>
        )}
      </span>
      <span className="visually-hidden">{`MovieLens average rating: ${value} out of 5, from ${ratings}`}</span>
    </span>
  )
}
