// Shown for any address that does not match a page (React Router's "*" route).

import { ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'

export function NotFoundPage() {
  return (
    <div className="container page">
      <title>Page not found · AuraCinema</title>
      {/* One h1 for screen readers; the empty state below is the visible message. */}
      <h1 className="visually-hidden">Page not found</h1>
      <EmptyState
        title="This reel is missing"
        description="The page you are looking for does not exist or has moved."
        action={<ButtonLink to="/">Back to Discover</ButtonLink>}
      />
    </div>
  )
}
