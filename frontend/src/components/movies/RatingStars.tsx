// Shows a rating as five stars, including half stars.
//
// AuraCinema ratings use the MovieLens scale: 0.5 to 5.0 in steps of 0.5
// (backend/app/schemas/rating.py). So 3.5 is drawn as three full stars, one
// half star and one empty star.
//
// This component only DISPLAYS a value. The interactive version (choosing a
// rating) belongs to the Rating phase. The value is also written for screen
// readers ("Rated 3.5 out of 5"), so it never depends on colour alone.

import styles from './RatingStars.module.css'

interface RatingStarsProps {
  /** A value from 0.5 to 5, or null when the movie has not been rated. */
  value: number | null
  size?: 'sm' | 'lg'
}

const STAR_PATH =
  'M12 2.8l2.75 5.57 6.15.9-4.45 4.33 1.05 6.12L12 16.83l-5.5 2.89 1.05-6.12L3.1 9.27l6.15-.9L12 2.8z'

export function RatingStars({ value, size = 'sm' }: RatingStarsProps) {
  const label = value === null ? 'Not rated yet' : `Rated ${value} out of 5`

  return (
    <span className={`${styles.stars} ${styles[size]}`} role="img" aria-label={label}>
      {[1, 2, 3, 4, 5].map((position) => {
        // How much of this star is filled: 1 = full, 0.5 = half, 0 = empty.
        const fill = value === null ? 0 : Math.min(Math.max(value - (position - 1), 0), 1)
        return (
          <span key={position} className={styles.star} aria-hidden="true">
            <svg viewBox="0 0 24 24" className={styles.empty} focusable="false">
              <path d={STAR_PATH} />
            </svg>
            {/* The filled star is drawn on top and cut to the right width. */}
            <span className={styles.fillClip} style={{ width: `${fill * 100}%` }}>
              <svg viewBox="0 0 24 24" className={styles.filled} focusable="false">
                <path d={STAR_PATH} />
              </svg>
            </span>
          </span>
        )
      })}
    </span>
  )
}
