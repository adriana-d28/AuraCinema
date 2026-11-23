// Account endpoints used by the authentication workflow.
//
// They follow the real backend contract (backend/app/api/routes/auth.py and
// users.py):
//   - POST /auth/register  JSON {name, email, password} -> 201 User (no token)
//   - POST /auth/login     FORM username=<email>, password -> TokenResponse
//   - GET  /users/me       Authorization: Bearer <token> -> User

import { apiRequest } from './client'
import type { RegisterRequest, TokenResponse, User } from './types'

export function registerRequest(data: RegisterRequest): Promise<User> {
  return apiRequest<User>('/auth/register', { method: 'POST', body: data })
}

export function loginRequest(email: string, password: string): Promise<TokenResponse> {
  // OAuth2 password flow: the email travels in the "username" form field.
  const form = new URLSearchParams({ username: email, password })
  return apiRequest<TokenResponse>('/auth/login', { method: 'POST', body: form })
}

export function getCurrentUser(token: string, signal?: AbortSignal): Promise<User> {
  return apiRequest<User>('/users/me', { token, signal })
}
