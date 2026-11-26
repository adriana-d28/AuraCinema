// Small helpers that turn raw catalogue values into text that reads well on screen.
//
// Since Phase 7.3 the readable title and the year come from the backend
// (display_title and year, built by backend/app/core/titles.py), so they are
// no longer worked out here.

/** Turn a runtime in minutes into "2h 50m" (or "45m" for short films). */
export function formatRuntime(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${rest}m`
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
}

// MovieLens lists "IMAX" among the genres, but it is a projection format, not
// a genre. The API keeps it (MovieLens is the source of truth, and Discovery
// Mode was evaluated with it), so the interface hides it, as agreed in
// decision Q4 of the intermediate backend phase.
const HIDDEN_GENRES = new Set(['IMAX'])

/** False for values that are listed as genres but are not shown as such (IMAX). */
export function isVisibleGenre(genre: string): boolean {
  return !HIDDEN_GENRES.has(genre)
}

/** The genres to show for a movie, without the hidden ones. */
export function visibleGenres(genres: string[]): string[] {
  return genres.filter(isVisibleGenre)
}
