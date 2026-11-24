// Discover: the catalogue-exploration entry point.
//
// Purpose of this page in the product: explore the CATALOGUE independently of
// personal recommendations - search, browse genres, open a movie.
// It deliberately has no "Popular", "Trending" or "Top rated" rows: ranked and
// personal lists belong to the Recommendations page, so the two pages never
// show the same lists.
//
// Data (Phase 7.3, public endpoints in services/api/movies.ts):
//   - featured movie: GET /movies/featured (hidden if there is none);
//   - genre chips:    GET /movies/genres;
//   - catalogue grid: GET /movies?search=&genre=&limit=20&offset=...
// The search text and the genre live in the address (/?search=matrix&genre=Sci-Fi),
// so going back from a movie's page shows the same results again. The backend
// accepts one genre at a time, so the chips work as a single choice that can
// be combined with the search. "Load more" asks for the next 20 movies.

import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { MovieCard } from '../components/movies/MovieCard'
import { MovieHero } from '../components/movies/MovieHero'
import { SearchInput } from '../components/ui/SearchInput'
import { SectionHeading } from '../components/ui/SectionHeading'
import { Skeleton } from '../components/ui/Skeleton'
import { StatusMessage } from '../components/ui/StatusMessage'
import { errorMessage, isAbortError } from '../services/api/client'
import { CATALOGUE_PAGE_SIZE, getFeaturedMovie, listGenres, listMovies } from '../services/api/movies'
import type { Genre, MovieDetails, MovieSummary } from '../services/api/types'
import styles from './DiscoverPage.module.css'

// Each result remembers which request (`key`) it answers. While the current
// search has no result yet, the page shows "loading", so no extra state update
// is needed when the search changes.
type CatalogueResult =
  | { key: string; status: 'error'; message: string }
  | { key: string; status: 'ready'; items: MovieSummary[]; total: number; loadMoreError: string | null }
type CatalogueState = { status: 'loading' } | CatalogueResult

export function DiscoverPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const search = searchParams.get('search') ?? ''
  const genre = searchParams.get('genre') ?? ''

  const [featured, setFeatured] = useState<MovieDetails | null>(null)
  const [genres, setGenres] = useState<Genre[]>([])
  const [genresFailed, setGenresFailed] = useState(false)
  const [result, setResult] = useState<CatalogueResult | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  // Increased by "Try again" to repeat the first-page request.
  const [attempt, setAttempt] = useState(0)
  const requestKey = JSON.stringify([search, genre, attempt])
  const catalogue: CatalogueState = result?.key === requestKey ? result : { status: 'loading' }
  // The running "Load more" request, cancelled when the search or genre changes.
  const loadMoreRequest = useRef<AbortController | null>(null)

  // Featured movie and genre list: loaded once. If either fails, the rest of
  // the page still works (the hero is simply not shown).
  useEffect(() => {
    const controller = new AbortController()
    getFeaturedMovie(controller.signal)
      .then(setFeatured)
      .catch(() => {}) // 404 (none qualifies) or any error: no hero.
    listGenres(controller.signal)
      .then(setGenres)
      .catch((error: unknown) => {
        if (!isAbortError(error)) setGenresFailed(true)
      })
    return () => controller.abort()
  }, [])

  // First page of the catalogue, again every time the search or the genre changes.
  useEffect(() => {
    const controller = new AbortController()
    loadMoreRequest.current?.abort()
    listMovies({ search, genre }, controller.signal)
      .then((page) =>
        setResult({ key: requestKey, status: 'ready', items: page.items, total: page.total, loadMoreError: null }),
      )
      .catch((error: unknown) => {
        if (!isAbortError(error)) setResult({ key: requestKey, status: 'error', message: errorMessage(error) })
      })
    return () => controller.abort()
  }, [search, genre, requestKey])

  async function loadMore() {
    if (catalogue.status !== 'ready' || loadingMore) return // No duplicate requests.
    const controller = new AbortController()
    loadMoreRequest.current = controller
    setLoadingMore(true)
    try {
      const page = await listMovies({ search, genre, offset: catalogue.items.length }, controller.signal)
      setResult({ ...catalogue, items: [...catalogue.items, ...page.items], total: page.total, loadMoreError: null })
    } catch (error) {
      // A cancelled request belonged to a previous search: nothing to show.
      if (!isAbortError(error)) setResult({ ...catalogue, loadMoreError: errorMessage(error) })
    } finally {
      setLoadingMore(false)
    }
  }

  /** Change the address; a value of "" removes that parameter. */
  function updateFilters(next: { search?: string; genre?: string }) {
    const params = new URLSearchParams()
    const nextSearch = next.search ?? search
    const nextGenre = next.genre ?? genre
    if (nextSearch) params.set('search', nextSearch)
    if (nextGenre) params.set('genre', nextGenre)
    setSearchParams(params)
  }

  const hasFilters = search !== '' || genre !== ''

  return (
    <>
      {/* React 19 moves <title> into the page <head> automatically. */}
      <title>Discover · AuraCinema</title>
      {/* The page heading for screen readers; the hero title is the visual focus. */}
      <h1 className="visually-hidden">Discover movies</h1>

      {/* 1. Featured movie: the cinematic introduction to the catalogue. */}
      {featured && (
        <MovieHero movie={featured} eyebrow="Featured from the catalogue">
          <ButtonLink to={`/movies/${featured.movie_id}`}>View details</ButtonLink>
          <ButtonLink to="#catalogue" variant="secondary">
            Browse catalogue
          </ButtonLink>
        </MovieHero>
      )}

      <div className="container page">
        {/* 2. Search: the main tool for finding a specific film. */}
        <section aria-labelledby="search-heading" className={styles.searchSection}>
          <SectionHeading
            id="search-heading"
            eyebrow="Search catalogue"
            title="Looking for a particular film?"
            description="Search the AuraCinema catalogue by title. Accents and punctuation do not matter."
          />
          {/* key: when the search changes from outside (Clear), the box shows the new value. */}
          <SearchInput
            key={search}
            label="Search movies by title"
            placeholder="Search by title"
            defaultValue={search}
            onSearch={(query) => updateFilters({ search: query })}
          />
        </section>

        {/* 3. Genres: a second way in, for users who do not have a title in mind. */}
        <section aria-labelledby="genres-heading">
          <SectionHeading id="genres-heading" eyebrow="Explore" title="Browse by genre" />
          {genresFailed ? (
            <p className={styles.note}>Genres could not be loaded. Search still works.</p>
          ) : (
            <ul role="list" className={styles.genres}>
              {genres.map(({ genre: name }) => (
                <li key={name}>
                  {/* aria-pressed tells screen readers whether the filter is on. */}
                  <button
                    type="button"
                    className={styles.genreChip}
                    aria-pressed={genre === name}
                    onClick={() => updateFilters({ genre: genre === name ? '' : name })}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 4. Catalogue: posters as the visual anchor of discovery. */}
        <section id="catalogue" aria-labelledby="catalogue-heading" className={styles.catalogue}>
          <SectionHeading
            id="catalogue-heading"
            eyebrow="The catalogue"
            title={hasFilters ? 'Results' : 'From the archive'}
            description={describeResults(catalogue, search, genre)}
            action={
              hasFilters && (
                <Button variant="ghost" size="sm" onClick={() => setSearchParams(new URLSearchParams())}>
                  Clear search and filters
                </Button>
              )
            }
          />

          {catalogue.status === 'loading' && (
            <>
              <p className="visually-hidden" role="status">
                Loading movies…
              </p>
              <ul role="list" className={styles.grid} aria-hidden="true">
                {Array.from({ length: 12 }, (_, index) => (
                  <li key={index}>
                    <Skeleton variant="poster" />
                  </li>
                ))}
              </ul>
            </>
          )}

          {catalogue.status === 'error' && (
            <EmptyState
              title="The catalogue could not be loaded"
              description={catalogue.message}
              action={
                <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>
                  Try again
                </Button>
              }
            />
          )}

          {catalogue.status === 'ready' && catalogue.items.length === 0 && (
            <EmptyState
              title="No films found"
              description="No film in the catalogue matches this search. Try another title or remove the genre filter."
              action={
                <Button variant="secondary" onClick={() => setSearchParams(new URLSearchParams())}>
                  Clear search and filters
                </Button>
              }
            />
          )}

          {catalogue.status === 'ready' && catalogue.items.length > 0 && (
            <>
              <ul role="list" className={styles.grid}>
                {catalogue.items.map((movie) => (
                  <li key={movie.movie_id}>
                    <MovieCard movie={movie} />
                  </li>
                ))}
              </ul>
              {catalogue.loadMoreError && <StatusMessage tone="error">{catalogue.loadMoreError}</StatusMessage>}
              {catalogue.items.length < catalogue.total && (
                <div className={styles.loadMore}>
                  <Button variant="secondary" onClick={loadMore} disabled={loadingMore}>
                    {loadingMore ? 'Loading…' : `Load ${Math.min(CATALOGUE_PAGE_SIZE, catalogue.total - catalogue.items.length)} more`}
                  </Button>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </>
  )
}

/** The line under the catalogue heading, e.g. 'Showing 20 of 41 films for "star" in Sci-Fi.' */
function describeResults(catalogue: CatalogueState, search: string, genre: string): string {
  if (catalogue.status !== 'ready') return 'Every film opens its own page.'
  const filters = [search && `for “${search}”`, genre && `in ${genre}`].filter(Boolean).join(' ')
  const count = `Showing ${catalogue.items.length} of ${catalogue.total.toLocaleString('en')} films`
  return filters ? `${count} ${filters}.` : `${count}. Every film opens its own page.`
}
