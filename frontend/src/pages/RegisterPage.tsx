// Register: create an AuraCinema account, shown inside AuthLayout.
//
// POST /api/v1/auth/register takes {name, email, password} and answers 201
// with the new account, but it does NOT sign the user in (no token). As
// agreed for Phase 7.2, the user is then sent to Log in, with a confirmation
// message and the email already filled in.
// Rules (backend contract): name 1-100 characters, password 15-128 characters.

import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import {
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  registrationErrorMessage,
  validateRegistration,
  type FieldErrors,
} from '../auth/validation'
import { Button } from '../components/ui/Button'
import { SectionHeading } from '../components/ui/SectionHeading'
import { TextField } from '../components/ui/TextField'
import { registerRequest } from '../services/api/auth'
import type { LoginPageState } from './LoginPage'
import styles from './AuthForm.module.css'

type Field = 'name' | 'email' | 'password'

export function RegisterPage() {
  const navigate = useNavigate()
  const [values, setValues] = useState<Record<Field, string>>({ name: '', email: '', password: '' })
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<Field>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function update(field: Field, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setFieldErrors((current) => ({ ...current, [field]: undefined }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return // Ignore extra clicks or Enter presses while waiting.

    const errors = validateRegistration(values.name, values.email, values.password)
    setFieldErrors(errors)
    setFormError(null)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      const user = await registerRequest({
        name: values.name.trim(),
        email: values.email.trim(),
        password: values.password,
      })
      // Only the (normalised) email is passed on; the password stays here.
      const state: LoginPageState = { registeredEmail: user.email }
      navigate('/login', { state })
    } catch (error) {
      setFormError(registrationErrorMessage(error))
      setSubmitting(false)
    }
  }

  return (
    <div className={styles.wrapper}>
      <title>Create account · AuraCinema</title>
      <SectionHeading as="h1" eyebrow="Create account" title="Join AuraCinema" />

      {formError && (
        <p className={styles.alert} role="alert">
          {formError}
        </p>
      )}

      <form className={styles.form} onSubmit={handleSubmit} noValidate>
        <TextField
          label="Name"
          autoComplete="name"
          required
          value={values.name}
          error={fieldErrors.name}
          onChange={(event) => update('name', event.target.value)}
        />
        <TextField
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={values.email}
          error={fieldErrors.email}
          onChange={(event) => update('email', event.target.value)}
        />
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
          minLength={PASSWORD_MIN_LENGTH}
          maxLength={PASSWORD_MAX_LENGTH}
          required
          value={values.password}
          error={fieldErrors.password}
          onChange={(event) => update('password', event.target.value)}
        />
        <div className={styles.actions}>
          <Button type="submit" disabled={submitting} aria-busy={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </Button>
        </div>
      </form>

      <p className={styles.switch}>
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </div>
  )
}
