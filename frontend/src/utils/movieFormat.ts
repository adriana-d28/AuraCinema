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
