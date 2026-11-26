// Client-side checks for the Login, Register and Settings forms, and friendly
// messages for failed account requests.
//
// The rules repeat the backend contract (backend/app/schemas/auth.py and
// schemas/common.py) so most mistakes are shown before a request is sent.
// The backend still validates everything; its 422 message is shown if a value
// passes here but not there (for example an unusual email address).

import { ApiError } from '../services/api/client'

export const PASSWORD_MIN_LENGTH = 15
export const PASSWORD_MAX_LENGTH = 128
export const NAME_MAX_LENGTH = 100
export const LOCATION_MAX_LENGTH = 100
export const BIO_MAX_LENGTH = 500

// A deliberately simple shape check ("something@something.something").
// The backend's email validator has the final word.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Python counts characters (code points), while JavaScript's .length counts
// UTF-16 units, so emoji would count twice. Spreading the string matches Python.
const characterCount = (value: string) => [...value].length

export type FieldErrors<Field extends string> = Partial<Record<Field, string>>

export function validateLogin(email: string, password: string): FieldErrors<'email' | 'password'> {
  const errors: FieldErrors<'email' | 'password'> = {}
  const emailError = checkEmail(email)
  if (emailError) errors.email = emailError
  if (password === '') errors.password = 'Enter your password.'
  return errors
}

export function validateRegistration(
  name: string,
  email: string,
  password: string,
): FieldErrors<'name' | 'email' | 'password'> {
  const errors: FieldErrors<'name' | 'email' | 'password'> = {}
  const nameError = checkName(name)
  if (nameError) errors.name = nameError

  const emailError = checkEmail(email)
  if (emailError) errors.email = emailError

  const passwordError = checkNewPassword(password)
  if (passwordError) errors.password = passwordError
  return errors
}

/** Settings, Profile information: name required; location and bio optional. */
export function validateProfile(
  name: string,
  location: string,
  bio: string,
): FieldErrors<'name' | 'location' | 'bio'> {
  const errors: FieldErrors<'name' | 'location' | 'bio'> = {}
  const nameError = checkName(name)
  if (nameError) errors.name = nameError

  const trimmedLocation = location.trim()
  if (characterCount(trimmedLocation) > LOCATION_MAX_LENGTH) {
    errors.location = `Use at most ${LOCATION_MAX_LENGTH} characters.`
  } else if (CONTROL_CHARACTER.test(trimmedLocation)) {
    errors.location = CONTROL_CHARACTER_MESSAGE
  }

  const trimmedBio = bio.trim()
  if (characterCount(trimmedBio) > BIO_MAX_LENGTH) {
    errors.bio = `Use at most ${BIO_MAX_LENGTH} characters.`
  } else if (CONTROL_CHARACTER.test(trimmedBio.replace(/\r?\n/g, ''))) {
    // Line breaks are allowed in the bio, as in the backend.
    errors.bio = CONTROL_CHARACTER_MESSAGE
  }
  return errors
}

/** Settings, Change email. */
export function validateEmailChange(
  newEmail: string,
  currentPassword: string,
): FieldErrors<'newEmail' | 'currentPassword'> {
  const errors: FieldErrors<'newEmail' | 'currentPassword'> = {}
  const emailError = checkEmail(newEmail)
  if (emailError) errors.newEmail = emailError
  if (currentPassword === '') errors.currentPassword = 'Enter your current password.'
  return errors
}

/** Settings, Change password. The confirmation is checked only here (the API receives one value). */
export function validatePasswordChange(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string,
): FieldErrors<'currentPassword' | 'newPassword' | 'confirmPassword'> {
  const errors: FieldErrors<'currentPassword' | 'newPassword' | 'confirmPassword'> = {}
  if (currentPassword === '') errors.currentPassword = 'Enter your current password.'
  const passwordError = checkNewPassword(newPassword)
  if (passwordError) errors.newPassword = passwordError
  if (confirmPassword !== newPassword) errors.confirmPassword = 'The two new passwords do not match.'
  return errors
}

const CONTROL_CHARACTER = /\p{Cc}/u
const CONTROL_CHARACTER_MESSAGE = 'Remove the special (control) characters.'

function checkName(name: string): string | undefined {
  const trimmedName = name.trim()
  if (trimmedName === '') return 'Enter your name.'
  if (characterCount(trimmedName) > NAME_MAX_LENGTH) return `Use at most ${NAME_MAX_LENGTH} characters.`
  if (CONTROL_CHARACTER.test(trimmedName)) return CONTROL_CHARACTER_MESSAGE
  return undefined
}

function checkNewPassword(password: string): string | undefined {
  const passwordLength = characterCount(password)
  if (passwordLength < PASSWORD_MIN_LENGTH) return `Use at least ${PASSWORD_MIN_LENGTH} characters.`
  if (passwordLength > PASSWORD_MAX_LENGTH) return `Use at most ${PASSWORD_MAX_LENGTH} characters.`
  return undefined
}

function checkEmail(email: string): string | undefined {
  if (email.trim() === '') return 'Enter your email address.'
  if (!EMAIL_PATTERN.test(email.trim())) return 'Enter a valid email address, e.g. name@example.com.'
  return undefined
}

const GENERIC_ERROR = 'Something went wrong. Please try again in a moment.'

export function loginErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_ERROR
  // One message for unknown email and wrong password, as the backend intends.
  if (error.status === 401) return 'Incorrect email or password.'
  if (error.status === 0) return error.message // The server could not be reached.
  if (error.status === 422) return 'Please check your email and password.'
  return GENERIC_ERROR
}

export function registrationErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_ERROR
  if (error.status === 409) return 'An account with this email already exists. Log in instead.'
  // 0 = server unreachable; 422 = the backend's own validation message.
  if (error.status === 0 || error.status === 422) return error.message
  return GENERIC_ERROR
}

/** Settings: the backend's answer to a failed account change, as a message for the user. */
export function accountErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_ERROR
  // 403 = wrong current password. The session continues (only 401 ends it).
  if (error.status === 403) return 'Your current password is incorrect.'
  if (error.status === 409) return 'Another account already uses this email address.'
  // 0 = server unreachable; 413 and 422 = the backend's own message (e.g. picture too large).
  if (error.status === 0 || error.status === 413 || error.status === 422) return error.message
  return GENERIC_ERROR
}
