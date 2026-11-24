// A short feedback message after an action: "Rating saved." or an error.
//
// tone "success" is announced politely by screen readers (role="status");
// tone "error" is announced at once (role="alert"). The meaning is always in
// the words, never in the colour alone. Same look as the Log in messages.

import type { ReactNode } from 'react'
import styles from './StatusMessage.module.css'

interface StatusMessageProps {
  tone: 'success' | 'error'
  children: ReactNode
}

export function StatusMessage({ tone, children }: StatusMessageProps) {
  return (
    <p className={`${styles.message} ${styles[tone]}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </p>
  )
}
