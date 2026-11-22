// The message shown when an area has nothing to display yet, for example an
// empty watchlist. A good empty state says what will appear here and offers
// the next useful step (the optional `action`, usually a ButtonLink).

import type { ReactNode } from 'react'
import styles from './EmptyState.module.css'

interface EmptyStateProps {
  title: string
  description?: ReactNode
  action?: ReactNode
  /** Heading level, so the empty state fits the page's heading order. */
  headingLevel?: 'h2' | 'h3'
}

export function EmptyState({ title, description, action, headingLevel = 'h2' }: EmptyStateProps) {
  const Heading = headingLevel
  return (
    <div className={styles.empty}>
      {/* Decorative frame icon (an empty film frame), hidden from screen readers. */}
      <svg className={styles.icon} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
        <rect x="9" y="6" width="30" height="36" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M9 13h30M9 35h30" stroke="currentColor" strokeWidth="1.5" />
        <path d="M14 9.5h2M20 9.5h2M26 9.5h2M32 9.5h2M14 38.5h2M20 38.5h2M26 38.5h2M32 38.5h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <Heading className={styles.title}>{title}</Heading>
      {description && <p className={styles.description}>{description}</p>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  )
}
