// Watchlist: films the user has saved to watch later (PLACEHOLDER).
//
// The backend already supports the watchlist (GET/PUT/DELETE
// /api/v1/watchlist), but it needs sign-in, which arrives in the next frontend
// phase. In the Watchlist phase this page will list the saved films with
// compact MovieCards and a "Remove" button on each (as in the wireframe).
//
// Note for that phase: GET /watchlist returns only movie IDs and dates, not
// titles or posters. Adding them to the response is listed for the
// intermediate backend phase (UI/UX specification, section 18).

import { ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { SectionHeading } from '../components/ui/SectionHeading'

export function WatchlistPage() {
  return (
    <div className="container page">
      <title>Watchlist · AuraCinema</title>
      <SectionHeading
        as="h1"
        eyebrow="Saved for later"
        title="Your watchlist"
        description="Films you want to watch, kept in one place."
      />
      <EmptyState
        title="Your watchlist is empty"
        description="Films you save from a movie's page will appear here. Saving films is connected in a later phase."
        action={<ButtonLink to="/" variant="secondary">Explore the catalogue</ButtonLink>}
      />
    </div>
  )
}
