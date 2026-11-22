// The heading at the top of a page or a page section.
//
// It follows the editorial pattern used across AuraCinema:
//   EYEBROW LABEL        <- small upper-case gold label (the "archive" touch)
//   Title                <- serif title (Playfair Display)
//   Short description    <- muted text
// plus an optional `action` on the right (a button or a badge).
//
// `as` picks the real heading level: "h1" for the page title, "h2" for a
// section. Pages keep exactly one h1, which helps screen-reader navigation.

import type { ReactNode } from 'react'
import styles from './SectionHeading.module.css'

interface SectionHeadingProps {
  title: string
  eyebrow?: string
  description?: ReactNode
  action?: ReactNode
  as?: 'h1' | 'h2'
  /** id of the heading, so a <section aria-labelledby="..."> can point to it. */
  id?: string
}

export function SectionHeading({ title, eyebrow, description, action, as = 'h2', id }: SectionHeadingProps) {
  const Heading = as
  return (
    <div className={styles.wrapper}>
      <div className={styles.text}>
        {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
        <Heading id={id} className={as === 'h1' ? styles.pageTitle : styles.sectionTitle}>
          {title}
        </Heading>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  )
}
