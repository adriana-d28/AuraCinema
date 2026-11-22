// A small label, e.g. "Sample data" or "Coming soon".
//
// Tones:
//   neutral - plain information
//   accent  - burgundy, for something that deserves attention
//   gold    - editorial labels (used sparingly)
//
// <ComingSoonBadge /> is the one consistent way to mark a feature that is shown
// but not available yet. It always uses the same words, so users learn its
// meaning, and the meaning is written in text (not shown by colour alone).

import type { ReactNode } from 'react'
import styles from './Badge.module.css'

type BadgeTone = 'neutral' | 'accent' | 'gold'

interface BadgeProps {
  tone?: BadgeTone
  children: ReactNode
}

export function Badge({ tone = 'neutral', children }: BadgeProps) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>
}

export function ComingSoonBadge() {
  return <Badge tone="gold">Coming soon</Badge>
}
