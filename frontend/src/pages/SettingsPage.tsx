// Settings: private account management, separate from the Profile page.
//
// Settings favours clarity over cinematic effects: plain panels and forms.
// Following the original wireframe it has three groups, each form with its
// own button, because each one uses a different endpoint (services/api/users.ts):
//   - Profile information: picture (uploaded/removed at once), name, location
//     and bio (PATCH /users/me; only the changed fields are sent).
//   - Account information: email and password. Both ask for the current
//     password (PUT /users/me/email, PUT /users/me/password). A wrong current
//     password is answered with 403, shown next to that field; it does not end
//     the session (only 401 does).
//   - Session: log out (forget the token in this browser; Phase 7.2).
// Every successful change updates the signed-in account (useAuth().updateUser),
// so the header and the Profile page show it at once.

import { useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useAuth } from '../auth/authContext'
import {
  accountErrorMessage,
  BIO_MAX_LENGTH,
  LOCATION_MAX_LENGTH,
  NAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  validateEmailChange,
  validatePasswordChange,
  validateProfile,
  type FieldErrors,
} from '../auth/validation'
import { ProfilePicture } from '../components/profile/ProfilePicture'
import { Button } from '../components/ui/Button'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
import { StatusMessage } from '../components/ui/StatusMessage'
import { TextField } from '../components/ui/TextField'
import { ApiError } from '../services/api/client'
import type { ProfileUpdate } from '../services/api/types'
import { changeEmail, changePassword, deletePicture, updateProfile, uploadPicture } from '../services/api/users'
import styles from './SettingsPage.module.css'

/** Feedback shown under a form after it was sent. */
type Feedback = { tone: 'success' | 'error'; text: string; profileLink?: boolean } | null

export function SettingsPage() {
  const { logout } = useAuth()

  return (
    <div className="container page">
      <title>Settings · AuraCinema</title>

      <SectionHeading
        as="h1"
        eyebrow="Private · only you can see this"
        title="Settings"
        description="Manage your profile and account details."
      />

      <div className={styles.layout}>
        <Panel title="Profile information">
          <PictureSettings />
          <ProfileForm />
        </Panel>

        <div className={styles.column}>
          <Panel title="Account information">
            <EmailForm />
            <hr className={styles.divider} />
            <PasswordForm />
          </Panel>

          <Panel title="Session">
            <p>Log out of AuraCinema on this device.</p>
            <div>
              <Button variant="secondary" onClick={logout}>
                Log out
              </Button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}

// ---------- Profile picture ----------

// The same rules as the backend (user_service.py), checked first here so the
// user gets an answer without sending a file that would be refused.
const PICTURE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const PICTURE_MAX_BYTES = 2 * 1024 * 1024

function PictureSettings() {
  const { token, user, updateUser } = useAuth()
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const hasPicture = Boolean(user?.picture_updated_at)

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    event.target.value = '' // Choosing the same file again must trigger a new upload.
    if (!file || !token) return
    if (!PICTURE_TYPES.includes(file.type)) {
      setFeedback({ tone: 'error', text: 'Choose a JPEG, PNG or WebP image.' })
      return
    }
    if (file.size > PICTURE_MAX_BYTES) {
      setFeedback({ tone: 'error', text: 'The picture must be 2 MB or smaller.' })
      return
    }
    setBusy(true)
    setFeedback(null)
    try {
      updateUser(await uploadPicture(token, file))
      setFeedback({ tone: 'success', text: 'Picture updated.' })
    } catch (error) {
      setFeedback({ tone: 'error', text: accountErrorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove() {
    if (!token || !user) return
    setBusy(true)
    setFeedback(null)
    try {
      await deletePicture(token)
      updateUser({ ...user, picture_updated_at: null })
      setFeedback({ tone: 'success', text: 'Picture removed.' })
    } catch (error) {
      setFeedback({ tone: 'error', text: accountErrorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={styles.pictureBlock}>
      <div className={styles.picture}>
        <ProfilePicture size="sm" />
        <div className={styles.pictureActions}>
          {/* The real file input is hidden; the button opens it, so it looks
              like the other buttons and is reachable with the keyboard. */}
          <input
            ref={inputRef}
            type="file"
            accept={PICTURE_TYPES.join(',')}
            className="visually-hidden"
            tabIndex={-1}
            aria-hidden="true"
            onChange={handleFile}
          />
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            aria-busy={busy}
            aria-describedby="picture-hint"
            onClick={() => inputRef.current?.click()}
          >
            {busy ? 'Saving…' : hasPicture ? 'Change picture' : 'Upload picture'}
          </Button>
          {hasPicture && (
            <Button variant="ghost" size="sm" disabled={busy} onClick={handleRemove}>
              Remove
            </Button>
          )}
        </div>
      </div>
      <p id="picture-hint" className={styles.hint}>
        JPEG, PNG or WebP, up to 2 MB. It is cropped to a square and only you can see it.
      </p>
      {feedback && <StatusMessage tone={feedback.tone}>{feedback.text}</StatusMessage>}
    </div>
  )
}

// ---------- Name, location and bio ----------

type ProfileField = 'name' | 'location' | 'bio'

function ProfileForm() {
  const { token, user, updateUser } = useAuth()
  const [values, setValues] = useState<Record<ProfileField, string>>({
    name: user?.name ?? '',
    location: user?.location ?? '',
    bio: user?.bio ?? '',
  })
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<ProfileField>>({})
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [submitting, setSubmitting] = useState(false)

  function update(field: ProfileField, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setFieldErrors((current) => ({ ...current, [field]: undefined }))
    setFeedback(null)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !token || !user) return

    const errors = validateProfile(values.name, values.location, values.bio)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    // Only the fields that changed are sent. An empty location or bio removes it.
    const changes: ProfileUpdate = {}
    const name = values.name.trim()
    const location = values.location.trim()
    const bio = values.bio.trim()
    if (name !== (user.name ?? '')) changes.name = name
    if (location !== (user.location ?? '')) changes.location = location
    if (bio !== (user.bio ?? '')) changes.bio = bio
    if (Object.keys(changes).length === 0) {
      setFeedback({ tone: 'success', text: 'There are no changes to save.' })
      return
    }

    setSubmitting(true)
    try {
      const updated = await updateProfile(token, changes)
      updateUser(updated)
      // Show the values as the backend stored them (trimmed).
      setValues({ name: updated.name ?? '', location: updated.location ?? '', bio: updated.bio ?? '' })
      setFeedback({ tone: 'success', text: 'Profile saved.', profileLink: true })
    } catch (error) {
      setFeedback({ tone: 'error', text: accountErrorMessage(error) })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <TextField
        label="Name"
        autoComplete="name"
        required
        maxLength={NAME_MAX_LENGTH}
        value={values.name}
        error={fieldErrors.name}
        onChange={(event) => update('name', event.target.value)}
      />
      <TextField
        label="Location"
        placeholder="e.g. Dublin, Ireland"
        maxLength={LOCATION_MAX_LENGTH}
        value={values.location}
        error={fieldErrors.location}
        onChange={(event) => update('location', event.target.value)}
      />
      <TextField
        label="Short bio"
        placeholder="A few words about your film taste"
        multiline
        hint={`Optional, up to ${BIO_MAX_LENGTH} characters.`}
        maxLength={BIO_MAX_LENGTH}
        value={values.bio}
        error={fieldErrors.bio}
        onChange={(event) => update('bio', event.target.value)}
      />
      <div>
        <Button type="submit" disabled={submitting} aria-busy={submitting}>
          {submitting ? 'Saving…' : 'Save profile'}
        </Button>
      </div>
      {feedback && (
        <StatusMessage tone={feedback.tone}>
          {feedback.text}
          {feedback.profileLink && (
            <>
              {' '}
              <Link to="/profile">View your profile</Link>
            </>
          )}
        </StatusMessage>
      )}
    </form>
  )
}

// ---------- Email ----------

type EmailField = 'newEmail' | 'currentPassword'

function EmailForm() {
  const { token, user, updateUser } = useAuth()
  const [values, setValues] = useState<Record<EmailField, string>>({ newEmail: '', currentPassword: '' })
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<EmailField>>({})
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [submitting, setSubmitting] = useState(false)

  function update(field: EmailField, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setFieldErrors((current) => ({ ...current, [field]: undefined }))
    setFeedback(null)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !token) return

    const errors = validateEmailChange(values.newEmail, values.currentPassword)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      updateUser(await changeEmail(token, values.newEmail.trim(), values.currentPassword))
      setValues({ newEmail: '', currentPassword: '' })
      setFeedback({ tone: 'success', text: 'Email updated. Use it the next time you log in.' })
    } catch (error) {
      // The wrong password and a taken email are shown next to their fields.
      if (error instanceof ApiError && error.status === 403) {
        setFieldErrors({ currentPassword: accountErrorMessage(error) })
      } else if (error instanceof ApiError && error.status === 409) {
        setFieldErrors({ newEmail: accountErrorMessage(error) })
      } else {
        setFeedback({ tone: 'error', text: accountErrorMessage(error) })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate aria-labelledby="email-form-heading">
      <h3 id="email-form-heading" className={styles.formHeading}>
        Change email
      </h3>
      <TextField
        label="New email"
        type="email"
        autoComplete="email"
        hint={user ? `Current email: ${user.email}` : undefined}
        required
        value={values.newEmail}
        error={fieldErrors.newEmail}
        onChange={(event) => update('newEmail', event.target.value)}
      />
      <TextField
        label="Current password"
        type="password"
        autoComplete="current-password"
        required
        value={values.currentPassword}
        error={fieldErrors.currentPassword}
        onChange={(event) => update('currentPassword', event.target.value)}
      />
      <div>
        <Button type="submit" disabled={submitting} aria-busy={submitting}>
          {submitting ? 'Saving…' : 'Update email'}
        </Button>
      </div>
      {feedback && <StatusMessage tone={feedback.tone}>{feedback.text}</StatusMessage>}
    </form>
  )
}

// ---------- Password ----------

type PasswordField = 'currentPassword' | 'newPassword' | 'confirmPassword'

const EMPTY_PASSWORDS: Record<PasswordField, string> = { currentPassword: '', newPassword: '', confirmPassword: '' }

function PasswordForm() {
  const { token } = useAuth()
  const [values, setValues] = useState<Record<PasswordField, string>>(EMPTY_PASSWORDS)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors<PasswordField>>({})
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [submitting, setSubmitting] = useState(false)

  function update(field: PasswordField, value: string) {
    setValues((current) => ({ ...current, [field]: value }))
    setFieldErrors((current) => ({ ...current, [field]: undefined }))
    setFeedback(null)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting || !token) return

    const errors = validatePasswordChange(values.currentPassword, values.newPassword, values.confirmPassword)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setSubmitting(true)
    try {
      await changePassword(token, values.currentPassword, values.newPassword)
      // Passwords are never kept after the request.
      setValues(EMPTY_PASSWORDS)
      setFeedback({ tone: 'success', text: 'Password changed. Use the new one the next time you log in.' })
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setFieldErrors({ currentPassword: accountErrorMessage(error) })
      } else {
        setFeedback({ tone: 'error', text: accountErrorMessage(error) })
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate aria-labelledby="password-form-heading">
      <h3 id="password-form-heading" className={styles.formHeading}>
        Change password
      </h3>
      <TextField
        label="Current password"
        type="password"
        autoComplete="current-password"
        required
        value={values.currentPassword}
        error={fieldErrors.currentPassword}
        onChange={(event) => update('currentPassword', event.target.value)}
      />
      <TextField
        label="New password"
        type="password"
        autoComplete="new-password"
        hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
        minLength={PASSWORD_MIN_LENGTH}
        maxLength={PASSWORD_MAX_LENGTH}
        required
        value={values.newPassword}
        error={fieldErrors.newPassword}
        onChange={(event) => update('newPassword', event.target.value)}
      />
      <TextField
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        maxLength={PASSWORD_MAX_LENGTH}
        required
        value={values.confirmPassword}
        error={fieldErrors.confirmPassword}
        onChange={(event) => update('confirmPassword', event.target.value)}
      />
      <div>
        <Button type="submit" disabled={submitting} aria-busy={submitting}>
          {submitting ? 'Saving…' : 'Change password'}
        </Button>
      </div>
      {feedback && <StatusMessage tone={feedback.tone}>{feedback.text}</StatusMessage>}
    </form>
  )
}
