// Client-side checks for the Login and Register forms, and friendly messages
// for failed authentication requests.
//
// The rules repeat the backend contract (backend/app/schemas/auth.py and
// schemas/common.py) so most mistakes are shown before a request is sent.
// The backend still validates everything; its 422 message is shown if a value
// passes here but not there (for example an unusual email address).

import { ApiError } from '../services/api/client'

export const PASSWORD_MIN_LENGTH = 15
export const PASSWORD_MAX_LENGTH = 128
export const NAME_MAX_LENGTH = 100

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
  const trimmedName = name.trim()
  if (trimmedName === '') {
    errors.name = 'Enter your name.'
  } else if (characterCount(trimmedName) > NAME_MAX_LENGTH) {
    errors.name = `Use at most ${NAME_MAX_LENGTH} characters.`
  } else if (/\p{Cc}/u.test(trimmedName)) {
    errors.name = 'Remove the special (control) characters.'
  }

  const emailError = checkEmail(email)
  if (emailError) errors.email = emailError

  const passwordLength = characterCount(password)
  if (passwordLength < PASSWORD_MIN_LENGTH) {
    errors.password = `Use at least ${PASSWORD_MIN_LENGTH} characters.`
  } else if (passwordLength > PASSWORD_MAX_LENGTH) {
    errors.password = `Use at most ${PASSWORD_MAX_LENGTH} characters.`
  }
  return errors
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
