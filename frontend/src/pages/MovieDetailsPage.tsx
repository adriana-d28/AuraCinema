// Movie details (PREVIEW for the demonstration movies, placeholder otherwise).
//
// The address is /movies/:movieId (for example /movies/6). In the Movie
// details phase this page will load GET /api/v1/movies/{id}/details. For now:
//   - movies from the demonstration data are shown with the final layout;
//   - any other ID shows a placeholder (no API request is made).
//
// As in the original wireframe, "Add to watchlist" and "Rate this film" are two
// separate actions in two separate places, so users never confuse them.
// Both are disabled until their phases (the backend already supports both).

import { useParams } from 'react-router'
import { Badge, ComingSoonBadge } from '../components/ui/Badge'
import { Button, ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/EmptyState'
import { MovieHero } from '../components/movies/MovieHero'
import { Panel } from '../components/ui/Panel'
import { RatingStars } from '../components/movies/RatingStars'
import { Skeleton } from '../components/ui/Skeleton'
import { findDemoMovie } from '../data/demoMovies'
import { formatMovieTitle } from '../utils/movieFormat'
import styles from './MovieDetailsPage.module.css'

export function MovieDetailsPage() {
  // useParams reads the ":movieId" part of the address as text.
  const { movieId } = useParams()
  const movie = findDemoMovie(Number(movieId))

  if (!movie) {
    return (
      <div className="container page">
        <title>Movie details · AuraCinema</title>
        <h1 className="visually-hidden">Movie details</h1>
        <div className={styles.loadingPreview} aria-hidden="true">
          <Skeleton variant="poster" />
          <div className={styles.loadingText}>
            <Skeleton width="60%" />
            <Skeleton width="35%" />
            <Skeleton width="90%" />
          </div>
        </div>
        <EmptyState
          title="Movie details are on their way"
          description="Full movie pages load from the catalogue in a later phase. For now, only the sample films on Discover have a preview."
          action={<ButtonLink to="/" variant="secondary">Back to Discover</ButtonLink>}
        />
      </div>
    )
  }

  const { title } = formatMovieTitle(movie.title)
  // FR-4: when TMDB details are missing, show the catalogue data calmly, without an error.
  const hasExtraDetails = movie.metadata_status === 'available'

  return (
    <>
      <title>{`${title} · AuraCinema`}</title>
      <MovieHero
        movie={movie}
        headingLevel="h1"
        eyebrow={
          <>
            Movie details <Badge>Sample data</Badge>
          </>
        }
      >
        <Button variant="secondary" disabled>
          Add to watchlist
        </Button>
        <ComingSoonBadge />
      </MovieHero>

      <div className="container page">
        {!hasExtraDetails && (
          <p className={styles.missingNote}>
            More information about this film, such as its poster and plot, is not available yet.
          </p>
        )}

        <Panel title="Rate this film" comingSoon className={styles.ratePanel}>
          <RatingStars value={null} size="lg" />
          <p>
            Rate from half a star to five stars. Your ratings shape your recommendations.
          </p>
        </Panel>
      </div>
    </>
  )
}
