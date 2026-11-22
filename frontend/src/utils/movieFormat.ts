// Small helpers that turn raw catalogue values into text that reads well on screen.
//
// MovieLens titles carry extra information that looks untidy in a cinematic
// layout, for example:
//   "Matrix, The (1999)"                          -> "The Matrix"  + 1999
//   "Twelve Monkeys (a.k.a. 12 Monkeys) (1995)"   -> "Twelve Monkeys" + 1995
// The backend keeps the original title untouched; this is display only.
// The rules follow backend/app/core/titles.py (parse_movielens_title), but
// only the parts needed for display are repeated here. The intermediate
// backend phase may expose a ready-made display title instead (see the UI/UX
// specification, section 18).

// Articles that MovieLens moves to the end of a title ("Matrix, The").
// Same list as TRAILING_ARTICLES in backend/app/core/titles.py.
const TRAILING_ARTICLES = [
  'The', 'A', 'An', // English
  'Les', 'La', 'Le', "L'", 'Un', 'Une', // French
  'El', 'Los', 'Las', // Spanish
  'Il', 'Lo', 'Gli', 'I', // Italian
  'Das', 'Der', 'Die', 'Ein', 'Eine', // German
  'O', 'Os', 'As', // Portuguese
  'De', 'Het', 'Een', // Dutch
  'Den', 'Det', 'En', 'Ett', // Scandinavian
]

// Escape characters with a special meaning in regular expressions (the "'" in "L'" is safe).
const articlePattern = TRAILING_ARTICLES.map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
const TRAILING_ARTICLE = new RegExp(`^(.+), (${articlePattern})$`, 'i')
// "(1995)" at the end; a few titles use a range such as "(2006-2007)".
const YEAR_AT_END = /^(.*?)\s*\((\d{4})(?:[-–]\d{0,4})?\)\s*$/
// One parenthesised group at the end, e.g. "(a.k.a. 12 Monkeys)".
const GROUP_AT_END = /^(.*\S)\s*\([^()]*\)$/

export interface DisplayTitle {
  /** Main title, ready to show: "The Matrix". */
  title: string
  /** Release year taken from the title, or null when there is none. */
  year: number | null
}

/** Move a trailing article back to the front: "Matrix, The" -> "The Matrix". */
function moveTrailingArticle(title: string): string {
  const match = TRAILING_ARTICLE.exec(title.trim())
  if (!match) return title.trim()
  const [, rest, article] = match
  // "L'" is joined without a space: "Atalante, L'" -> "L'Atalante".
  return article.endsWith("'") ? `${article}${rest}` : `${article} ${rest}`
}

/** Split a MovieLens title into a clean display title and its year. */
export function formatMovieTitle(rawTitle: string): DisplayTitle {
  let rest = rawTitle.trim()
  let year: number | null = null

  const yearMatch = YEAR_AT_END.exec(rest)
  if (yearMatch && yearMatch[1]) {
    rest = yearMatch[1]
    year = Number(yearMatch[2])
  }

  // Drop alternative titles in brackets, which are often in another language.
  let groupMatch = GROUP_AT_END.exec(rest)
  while (groupMatch) {
    rest = groupMatch[1]
    groupMatch = GROUP_AT_END.exec(rest)
  }

  return { title: moveTrailingArticle(rest), year }
}

/** Turn a runtime in minutes into "2h 50m" (or "45m" for short films). */
export function formatRuntime(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours === 0) return `${rest}m`
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`
}
