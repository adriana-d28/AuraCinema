// A grey placeholder shape shown while content is loading.
//
// It keeps the space of the content that will arrive, so the page does not
// "jump" when the data appears. It is hidden from screen readers (the page
// announces loading with text instead). The soft shimmer animation is turned
// off for users who prefer reduced motion (see global.css).
//
// variant "poster" has the 2:3 poster shape; variant "text" is one line of text.

import styles from './Skeleton.module.css'

interface SkeletonProps {
  variant?: 'poster' | 'text'
  /** Width of a text line, e.g. "60%". Ignored for posters, which fill their column. */
  width?: string
}

export function Skeleton({ variant = 'text', width }: SkeletonProps) {
  return (
    <span
      className={`${styles.skeleton} ${styles[variant]}`}
      style={variant === 'text' && width ? { width } : undefined}
      aria-hidden="true"
    />
  )
}
