// Log in (PLACEHOLDER with the final form).
//
// Shown inside AuthLayout. POST /api/v1/auth/login already exists (it expects
// a form with "username" = email and "password"); the Authentication phase
// will connect this form, store the token and protect the private pages.
// Until then "Log in" is disabled.

import { Link } from 'react-router'
import { Button } from '../components/ui/Button'
import { SectionHeading } from '../components/ui/SectionHeading'
import { TextField } from '../components/ui/TextField'
import styles from './AuthForm.module.css'

export function LoginPage() {
  return (
    <div className={styles.wrapper}>
      <title>Log in · AuraCinema</title>
      <SectionHeading as="h1" eyebrow="Welcome back" title="Log in" />

      <form className={styles.form} onSubmit={(event) => event.preventDefault()} noValidate>
        <TextField label="Email" type="email" autoComplete="email" required />
        <TextField label="Password" type="password" autoComplete="current-password" required />
        <div className={styles.actions}>
          <Button type="submit" disabled>
            Log in
          </Button>
          <p className={styles.note}>Signing in is connected in the next frontend phase.</p>
        </div>
      </form>

      <p className={styles.switch}>
        New to AuraCinema? <Link to="/register">Create an account</Link>
      </p>
    </div>
  )
}
