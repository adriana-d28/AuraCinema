// A framed area that groups related content: "Account information",
// "Rate this film", "Discovery Mode"...
//
// `comingSoon` shows the "Coming soon" badge next to the title and gives the
// panel a dashed border, the shared visual sign of "planned, not available yet".

import type { ReactNode } from 'react'
import { ComingSoonBadge } from './Badge'
import styles from './Panel.module.css'

interface PanelProps {
  title: string
  children: ReactNode
  comingSoon?: boolean
  /** Extra element shown next to the title (for example a different badge). */
  badge?: ReactNode
  className?: string
}

export function Panel({ title, children, comingSoon = false, badge, className }: PanelProps) {
  const classes = [styles.panel, comingSoon && styles.planned, className].filter(Boolean).join(' ')
  return (
    <section className={classes}>
      <header className={styles.header}>
        <h2 className={styles.title}>{title}</h2>
        {comingSoon ? <ComingSoonBadge /> : badge}
      </header>
      <div className={styles.body}>{children}</div>
    </section>
  )
}
