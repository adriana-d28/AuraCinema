// Log in, shown inside AuthLayout.
//
// The form sends the credentials through useAuth().login(), which calls
// POST /api/v1/auth/login and stores the session (src/auth/AuthProvider.tsx).
// On success nothing needs to happen here: the RedirectIfAuthenticated guard
// sees the new session and opens the page the user originally asked for, or
// Discover (src/auth/RouteGuards.tsx).

import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router'
import { useAuth } from '../auth/authContext'
import type { LoginRedirectState } from '../auth/RouteGuards'
import { loginErrorMessage, validateLogin, type FieldErrors } from '../auth/validation'
import { Button } from '../components/ui/Button'
import { SectionHeading } from '../components/ui/SectionHeading'
import { TextField } from '../components/ui/TextField'
import styles from './AuthForm.module.css'

/** Location state this page understands: the guard's `from`, or the email of a new account. */
export interface LoginPageState extends LoginRedirectState {
  registeredEmail?: string
}

export function LoginPage() {
  const { login, endReason } = useAuth()
  const location = useLocation()
  const registeredEmail = (location.state as LoginPageState | null)?.registeredEmail

  const [email, setEmail] = useState(registeredEmail ?? '')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<'email' | 'password'>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // A short confirmation about what just happened, if anything.
  let notice: string | null = null
  if (registeredEmail) notice = 'Account created. Log in with your new password.'
  else if (endReason === 'logout') notice = 'You have logged out.'
  else if (endReason === 'expired') notice = 'Your session has ended. Please log in again.'

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return // Ignore extra clicks or Enter presses while waiting.

    const errors = validateLogin(email, password)
    setFieldErrors(errors)
    setFormError(null)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      await login(email.trim(), password)
      // Success: the guard redirects and this page is removed.
    } catch (error) {
      setFormError(loginErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.wrapper}>
      <title>Log in · AuraCinema</title>
      <SectionHeading as="h1" eyebrow="Welcome back" title="Log in" />

      {notice && !formError && (
        <p className={styles.success} role="status">
          {notice}
        </p>
      )}
      {formError && (
        <p className={styles.alert} role="alert">
          {formError}
        </p>
      )}

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          error={fieldErrors.email}
          onChange={(event) => {
            setEmail(event.target.value)
            setFieldErrors((current) => ({ ...current, email: undefined }))
          }}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          error={fieldErrors.password}
          onChange={(event) => {
            setPassword(event.target.value)
            setFieldErrors((current) => ({ ...current, password: undefined }))
          }}
        />
        <div className={styles.actions}>
          <Button type="submit" disabled={submitting} aria-busy={submitting}>
            {submitting ? 'Logging in…' : 'Log in'}
          </Button>
        </div>
      </form>

      <p className={styles.switch}>
        New to AuraCinema? <Link to="/register">Create an account</Link>
      </p>
    </div>
  )
}
