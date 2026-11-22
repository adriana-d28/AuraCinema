// Discover: the catalogue-exploration entry point (VISUAL DEMONSTRATION).
//
// Purpose of this page in the product: explore the CATALOGUE independently of
// personal recommendations - search, browse genres, open a movie.
// It deliberately has no "Popular", "Trending" or "Top rated" rows: ranked and
// personal lists belong to the Recommendations page, so the two pages never
// show the same lists.
//
// Phase 7.1 status:
//   - Featured area, catalogue grid: built with the demonstration data in
//     src/data/demoMovies.ts (real catalogue values, no API request).
//   - Search: the box can be typed in, but the Search button is disabled until
//     the catalogue phase connects it to GET /api/v1/movies?search=...
//   - Filters and genre chips: disabled. The API has no genre filter or genre
//     list yet; they are planned for the intermediate backend phase.

import { Badge, ComingSoonBadge } from '../components/ui/Badge'
import { Button, ButtonLink } from '../components/ui/Button'
import { MovieCard } from '../components/movies/MovieCard'
import { MovieHero } from '../components/movies/MovieHero'
import { SearchInput } from '../components/ui/SearchInput'
import { SectionHeading } from '../components/ui/SectionHeading'
import { CATALOGUE_GENRES, demoCatalogueMovies, demoFeaturedMovie } from '../data/demoMovies'
import styles from './DiscoverPage.module.css'

export function DiscoverPage() {
  return (
    <>
      {/* React 19 moves <title> into the page <head> automatically. */}
      <title>Discover · AuraCinema</title>
      {/* The page heading for screen readers; the hero title is the visual focus. */}
      <h1 className="visually-hidden">Discover movies</h1>

      {/* 1. Featured movie: the cinematic introduction to the catalogue. */}
      <MovieHero
        movie={demoFeaturedMovie}
        eyebrow={
          <>
            Featured from the catalogue <Badge>Sample data</Badge>
          </>
        }
      >
        <ButtonLink to={`/movies/${demoFeaturedMovie.movie_id}`}>View details</ButtonLink>
        <ButtonLink to="#catalogue" variant="secondary">
          Browse catalogue
        </ButtonLink>
      </MovieHero>

      <div className="container page">
        {/* 2. Search: the main tool for finding a specific film. */}
        <section aria-labelledby="search-heading" className={styles.searchSection}>
          <SectionHeading
            id="search-heading"
            eyebrow="Search catalogue"
            title="Looking for a particular film?"
            description="Search the 5,068 films of the AuraCinema catalogue by title."
          />
          <div className={styles.searchRow}>
            <SearchInput
              label="Search movies by title"
              placeholder="Search by title"
              hint="Search will be connected in the catalogue phase."
              submitDisabled
            />
            <div className={styles.filters}>
              <Button variant="secondary" disabled>
                Filters
              </Button>
              <ComingSoonBadge />
            </div>
          </div>
        </section>

        {/* 3. Genres: a second way in, for users who do not have a title in mind. */}
        <section aria-labelledby="genres-heading">
          <SectionHeading
            id="genres-heading"
            eyebrow="Explore"
            title="Browse by genre"
            action={<ComingSoonBadge />}
          />
          <ul role="list" className={styles.genres}>
            {CATALOGUE_GENRES.map((genre) => (
              <li key={genre}>
                <button type="button" className={styles.genreChip} disabled>
                  {genre}
                </button>
              </li>
            ))}
          </ul>
        </section>

        {/* 4. Catalogue sample: posters as the visual anchor of discovery. */}
        <section id="catalogue" aria-labelledby="catalogue-heading" className={styles.catalogue}>
          <SectionHeading
            id="catalogue-heading"
            eyebrow="The catalogue"
            title="From the archive"
            description="A first look at the catalogue. Every film opens its own page."
            action={<Badge>Sample data</Badge>}
          />
          <ul role="list" className={styles.grid}>
            {demoCatalogueMovies.map((movie) => (
              <li key={movie.movie_id}>
                <MovieCard movie={movie} />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  )
}
