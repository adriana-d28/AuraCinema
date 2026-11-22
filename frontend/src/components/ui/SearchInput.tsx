// The catalogue search box.
//
// It is a real <form role="search">, so screen readers list it as the page's
// search area and pressing Enter submits it. The label is visually hidden
// (the magnifying-glass icon and the placeholder already show what it is for)
// but still read aloud.
//
// Phase 7.1: the Discover preview passes `submitDisabled`, because catalogue
// search is connected to GET /api/v1/movies?search=... in the catalogue phase.
// In that phase the page will pass an `onSearch` function instead.

import { useId, useState, type FormEvent } from 'react'
import { Button } from './Button'
import styles from './SearchInput.module.css'

interface SearchInputProps {
  label: string
  placeholder?: string
  hint?: string
  /** Called with the trimmed text when the form is submitted. */
  onSearch?: (query: string) => void
  /** Keeps the input usable but disables the submit button (feature not connected yet). */
  submitDisabled?: boolean
}

export function SearchInput({ label, placeholder, hint, onSearch, submitDisabled = false }: SearchInputProps) {
  const inputId = useId()
  const hintId = `${inputId}-hint`
  const [query, setQuery] = useState('')

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    // Stop the browser from reloading the page (the default form behaviour).
    event.preventDefault()
    if (submitDisabled) return
    onSearch?.(query.trim())
  }

  return (
    <form role="search" className={styles.form} onSubmit={handleSubmit}>
      <label htmlFor={inputId} className="visually-hidden">
        {label}
      </label>
      <div className={styles.inputWrap}>
        {/* Decorative icon: hidden from screen readers. */}
        <svg className={styles.icon} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          <path d="m16 16 4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
        <input
          id={inputId}
          type="search"
          className={styles.input}
          placeholder={placeholder}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-describedby={hint ? hintId : undefined}
          maxLength={100} // Same maximum as the backend search parameter.
          autoComplete="off"
        />
        <Button type="submit" className={styles.submit} disabled={submitDisabled}>
          Search
        </Button>
      </div>
      {hint && (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      )}
    </form>
  )
}
