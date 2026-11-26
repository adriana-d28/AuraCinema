// A form field: a visible label, the input itself and an optional hint below.
//
// - The label is always connected to the input (htmlFor + id), so clicking the
//   label focuses the input and screen readers read the label aloud.
// - The hint is connected with aria-describedby, so it is read too.
// - `comingSoon` marks a field the backend does not support yet (for example
//   "Name" during registration): the field is disabled and shows the badge.
// - `multiline` renders a <textarea> instead of an <input> (for a bio). It
//   receives the same props as the input (value, onChange, maxLength...).
// - `error` shows a validation message under the field. The input is marked
//   aria-invalid and the message is read together with the label.

import { useId, type InputHTMLAttributes } from 'react'
import { ComingSoonBadge } from './Badge'
import styles from './TextField.module.css'

// Event handlers receive either element, so one onChange works for both.
interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement | HTMLTextAreaElement> {
  label: string
  hint?: string
  error?: string
  comingSoon?: boolean
  multiline?: boolean
}

export function TextField({
  label,
  hint,
  error,
  comingSoon = false,
  multiline = false,
  id,
  disabled,
  className,
  type,
  ...inputProps
}: TextFieldProps) {
  // useId creates a unique id, so two fields never share one by mistake.
  const generatedId = useId()
  const fieldId = id ?? generatedId
  const hintId = hint ? `${fieldId}-hint` : undefined
  const errorId = error ? `${fieldId}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined
  const isDisabled = disabled || comingSoon

  return (
    <div className={[styles.field, className].filter(Boolean).join(' ')}>
      <div className={styles.labelRow}>
        <label htmlFor={fieldId} className={styles.label}>
          {label}
        </label>
        {comingSoon && <ComingSoonBadge />}
      </div>

      {multiline ? (
        <textarea
          id={fieldId}
          className={styles.control}
          rows={3}
          disabled={isDisabled}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...inputProps}
        />
      ) : (
        <input
          id={fieldId}
          type={type}
          className={styles.control}
          disabled={isDisabled}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...inputProps}
        />
      )}

      {hint && (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} className={styles.error}>
          {error}
        </p>
      )}
    </div>
  )
}
