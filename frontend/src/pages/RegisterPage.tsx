// Register: create an AuraCinema account (PLACEHOLDER with the final form).
//
// Shown inside AuthLayout. The fields follow the original wireframe:
//   - Name      [needs backend] accounts have no name field yet, so the input
//               is disabled with "Coming soon" (intermediate backend phase);
//   - Email     [later frontend phase] POST /api/v1/auth/register exists;
//   - Password  [later frontend phase] the backend requires 15-128 characters.
// "Create account" stays disabled until the Authentication phase connects
// the form. After a successful registration the user will go to Discover.

import { Link } from 'react-router'
import { Button } from '../components/ui/Button'
import { SectionHeading } from '../components/ui/SectionHeading'
import { TextField } from '../components/ui/TextField'
import styles from './AuthForm.module.css'

export function RegisterPage() {
  return (
    <div className={styles.wrapper}>
      <title>Create account · AuraCinema</title>
      <SectionHeading as="h1" eyebrow="Create account" title="Join AuraCinema" />

      <form className={styles.form} onSubmit={(event) => event.preventDefault()} noValidate>
        <TextField label="Name" autoComplete="name" comingSoon />
        <TextField label="Email" type="email" autoComplete="email" required />
        <TextField
          label="Password"
          type="password"
          autoComplete="new-password"
          hint="At least 15 characters."
          minLength={15}
          maxLength={128}
          required
        />
        <div className={styles.actions}>
          <Button type="submit" disabled>
            Create account
          </Button>
          <p className={styles.note}>Account creation is connected in the next frontend phase.</p>
        </div>
      </form>

      <p className={styles.switch}>
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </div>
  )
}
