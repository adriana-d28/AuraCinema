// Lets the user CHOOSE a rating, drawn as five stars with half steps.
//
// The backend scale is 0.5 to 5.0 in steps of 0.5 (backend/app/schemas/rating.py),
// so there are ten choices. Each star has two halves, and each half is a real
// radio button (hidden visually, still used by keyboards and screen readers):
//   - Tab moves into the group, the arrow keys change the choice;
//   - every option is announced as "3.5 stars", never by colour alone.
// The component only reports the choice (onChange). Saving it is the page's job.

import { useId } from 'react'
import { STAR_PATH } from './RatingStars'
import styles from './RatingInput.module.css'

interface RatingInputProps {
  /** The chosen value (0.5 to 5), or null when nothing is chosen yet. */
  value: number | null
  onChange: (value: number) => void
  disabled?: boolean
  /** Name of the group for screen readers, e.g. "Your rating for Heat". */
  label: string
}

export function RatingInput({ value, onChange, disabled = false, label }: RatingInputProps) {
  const name = useId()

  return (
    <fieldset className={styles.group} disabled={disabled}>
      <legend className="visually-hidden">{label}</legend>
      {[1, 2, 3, 4, 5].map((position) => {
        const fill = value === null ? 0 : Math.min(Math.max(value - (position - 1), 0), 1)
        return (
          <span key={position} className={styles.star}>
            {/* Drawing of the star (decorative): filled 0%, 50% or 100%. */}
            <svg viewBox="0 0 24 24" className={styles.empty} aria-hidden="true" focusable="false">
              <path d={STAR_PATH} />
            </svg>
            <span className={styles.fillClip} style={{ width: `${fill * 100}%` }} aria-hidden="true">
              <svg viewBox="0 0 24 24" className={styles.filled} focusable="false">
                <path d={STAR_PATH} />
              </svg>
            </span>
            {/* The two clickable halves: left = position - 0.5, right = position. */}
            {[position - 0.5, position].map((option) => (
              <label key={option} className={option % 1 === 0 ? styles.right : styles.left}>
                <input
                  type="radio"
                  name={name}
                  value={option}
                  checked={value === option}
                  onChange={() => onChange(option)}
                  className="visually-hidden"
                />
                <span className="visually-hidden">{`${option} ${option === 1 ? 'star' : 'stars'}`}</span>
              </label>
            ))}
          </span>
        )
      })}
    </fieldset>
  )
}
