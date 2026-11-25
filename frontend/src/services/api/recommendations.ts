// Recommendation endpoint (backend/app/api/routes/recommendations.py). Login
// required: the backend uses the signed-in user's own ratings, never a user ID
// sent by the client.
//   - GET /recommendations                                       -> plain recommendations
//   - GET /recommendations?discovery_mode=safe|balanced|adventurous -> Discovery Mode on
//     (503 when the recommendation service is unavailable)
// The backend chooses the recommender (collaborative filtering or the
// popularity baseline) and applies Discovery Mode to personalised lists only.

import { apiRequest } from './client'
import type { DiscoveryMode, RecommendationResponse } from './types'

/** `discoveryMode` null = Discovery Mode off: the parameter is not sent at all. */
export function getMyRecommendations(
  token: string,
  discoveryMode: DiscoveryMode | null,
  signal?: AbortSignal,
): Promise<RecommendationResponse> {
  const query = discoveryMode ? `?${new URLSearchParams({ discovery_mode: discoveryMode })}` : ''
  return apiRequest<RecommendationResponse>(`/recommendations${query}`, { token, signal })
}
