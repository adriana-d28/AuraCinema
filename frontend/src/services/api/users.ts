// Endpoints of the signed-in user's own account (backend/app/api/routes/users.py),
// used by the Profile and Settings pages. Every call needs the login token and
// acts only on that user: there is no user ID in any path.
//   - PATCH  /users/me           JSON {name?, location?, bio?} -> User
//   - PUT    /users/me/email     JSON {new_email, current_password} -> User
//                                (403 wrong password, 409 email taken)
//   - PUT    /users/me/password  JSON {current_password, new_password} -> 204
//                                (403 wrong password)
//   - GET    /users/me/stats     -> UserStatistics
//   - PUT    /users/me/picture   multipart field "picture" -> User
//                                (413 over 2 MB, 422 not a JPEG/PNG/WebP image)
//   - GET    /users/me/picture   -> the image (404 when there is none)
//   - DELETE /users/me/picture   -> 204
//
// A wrong current password is answered with 403, not 401, so it never ends
// the session (only 401 does, in client.ts).

import { apiRequest } from './client'
import type { ProfileUpdate, User, UserStatistics } from './types'

export function updateProfile(token: string, changes: ProfileUpdate): Promise<User> {
  return apiRequest<User>('/users/me', { method: 'PATCH', body: changes, token })
}

export function changeEmail(token: string, newEmail: string, currentPassword: string): Promise<User> {
  return apiRequest<User>('/users/me/email', {
    method: 'PUT',
    body: { new_email: newEmail, current_password: currentPassword },
    token,
  })
}

export function changePassword(token: string, currentPassword: string, newPassword: string): Promise<void> {
  return apiRequest<void>('/users/me/password', {
    method: 'PUT',
    body: { current_password: currentPassword, new_password: newPassword },
    token,
  })
}

export function getMyStatistics(token: string, signal?: AbortSignal): Promise<UserStatistics> {
  return apiRequest<UserStatistics>('/users/me/stats', { token, signal })
}

export function uploadPicture(token: string, file: File): Promise<User> {
  const form = new FormData()
  form.append('picture', file)
  return apiRequest<User>('/users/me/picture', { method: 'PUT', body: form, token })
}

/** The picture as a Blob. An <img> cannot send the login token, so it is fetched here. */
export function getPicture(token: string, signal?: AbortSignal): Promise<Blob> {
  return apiRequest<Blob>('/users/me/picture', { token, signal, responseType: 'blob' })
}

export function deletePicture(token: string): Promise<void> {
  return apiRequest<void>('/users/me/picture', { method: 'DELETE', token })
}
