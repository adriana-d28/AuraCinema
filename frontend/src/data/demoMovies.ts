// ============================================================================
//  DEMONSTRATION DATA — NOT LOADED FROM THE API
// ============================================================================
//
// Phase 7.1 only builds the visual foundation, so the Discover preview and the
// movie details preview use this fixed list instead of calling the backend.
//
// The values are REAL: they were copied on 22 November 2026 from the
// development database (the same values GET /api/v1/movies/{id}/details
// returns). One simplification: metadata_updated_at uses the same import
// time for all movies (the real values differ by a few seconds), because the
// interface never shows it. Every object has the exact shape of the API type MovieDetails, so
// in the catalogue phase this file can be replaced by real API calls without
// changing the components.
//
// Two movies deliberately have no poster, exactly as in the database today:
//   - 2571 The Matrix: metadata not imported yet (only 40 movies have
//     metadata, see the UI/UX specification, section 10);
//   - 7842 Dune (2000): no TMDB ID in the catalogue.
// They show how the poster placeholder behaves inside a grid.
//
// Poster images are loaded by the browser from image.tmdb.org, as the backend
// documentation describes. No new image source is introduced.

import type { MovieDetails } from '../services/api/types'

const POSTER_BASE_URL = 'https://image.tmdb.org/t/p/w500'

/** Builds a demo movie that has stored TMDB metadata (status "available"). */
function withMetadata(
  movie: Pick<MovieDetails, 'movie_id' | 'title' | 'genres' | 'tmdb_id' | 'imdb_id'> & {
    overview: string
    release_date: string
    runtime: number
    poster_path: string
    tmdb_validation_status: string
  },
): MovieDetails {
  return {
    ...movie,
    poster_url: `${POSTER_BASE_URL}${movie.poster_path}`,
    metadata_status: 'available',
    metadata_updated_at: '2026-11-06T19:13:12Z', // simplified, see the note at the top
  }
}

/** The movie shown in the large featured area at the top of Discover. */
export const demoFeaturedMovie: MovieDetails = withMetadata({
  movie_id: 6,
  title: 'Heat (1995)',
  genres: ['Action', 'Crime', 'Thriller'],
  tmdb_id: 949,
  imdb_id: 113277,
  overview:
    'Obsessive master thief Neil McCauley leads a top-notch crew on various daring heists throughout Los Angeles while determined detective Vincent Hanna pursues him without rest. Each man recognizes and respects the ability and the dedication of the other even though they are aware their cat-and-mouse game may end in violence.',
  release_date: '1995-12-15',
  runtime: 170,
  poster_path: '/umSVjVdbVwtx5ryCA2QXL44Durm.jpg',
  tmdb_validation_status: 'valid',
})

/** A small sample of the catalogue for the Discover grid. */
export const demoCatalogueMovies: MovieDetails[] = [
  withMetadata({
    movie_id: 32,
    title: 'Twelve Monkeys (a.k.a. 12 Monkeys) (1995)',
    genres: ['Mystery', 'Sci-Fi', 'Thriller'],
    tmdb_id: 63,
    imdb_id: 114746,
    overview:
      "In the year 2035, convict James Cole reluctantly volunteers to be sent back in time to discover the origin of a deadly virus that wiped out nearly all of the earth's population and forced the survivors into underground communities.",
    release_date: '1995-12-29',
    runtime: 129,
    poster_path: '/gt3iyguaCIw8DpQZI1LIN5TohM2.jpg',
    tmdb_validation_status: 'not_checked',
  }),
  withMetadata({
    movie_id: 16,
    title: 'Casino (1995)',
    genres: ['Crime', 'Drama'],
    tmdb_id: 524,
    imdb_id: 112641,
    overview:
      'In Las Vegas, two best friends-a casino executive and a Mafia enforcer--compete for a gambling empire and a fast-living, fast-loving socialite.',
    release_date: '1995-11-22',
    runtime: 179,
    poster_path: '/gziIkUSnYuj9ChCi8qOu2ZunpSC.jpg',
    tmdb_validation_status: 'valid',
  }),
  withMetadata({
    movie_id: 29,
    title: 'City of Lost Children, The (Cité des enfants perdus, La) (1995)',
    genres: ['Adventure', 'Drama', 'Fantasy', 'Mystery', 'Sci-Fi'],
    tmdb_id: 902,
    imdb_id: 112682,
    overview:
      'A scientist in a surrealist society kidnaps children to steal their dreams, hoping that they slow his aging process.',
    release_date: '1995-05-17',
    runtime: 112,
    poster_path: '/zwTqStZ0wCDoi5hD1wZjJjUKtFq.jpg',
    tmdb_validation_status: 'not_checked',
  }),
  withMetadata({
    movie_id: 22,
    title: 'Copycat (1995)',
    genres: ['Crime', 'Drama', 'Horror', 'Mystery', 'Thriller'],
    tmdb_id: 1710,
    imdb_id: 112722,
    overview:
      'An agoraphobic psychologist and a female detective must work together to take down a serial killer who copies serial killers from the past.',
    release_date: '1995-10-27',
    runtime: 124,
    poster_path: '/oMgwJb016znNZcpDR20eXxZoW8A.jpg',
    tmdb_validation_status: 'not_checked',
  }),
  {
    // No poster yet: metadata not imported (real current state of the database).
    movie_id: 2571,
    title: 'Matrix, The (1999)',
    genres: ['Action', 'Sci-Fi', 'Thriller'],
    tmdb_id: 603,
    imdb_id: 133093,
    overview: null,
    release_date: null,
    runtime: null,
    poster_path: null,
    poster_url: null,
    metadata_status: 'not_imported',
    metadata_updated_at: null,
    tmdb_validation_status: 'not_checked',
  },
  withMetadata({
    movie_id: 25,
    title: 'Leaving Las Vegas (1995)',
    genres: ['Drama', 'Romance'],
    tmdb_id: 451,
    imdb_id: 113627,
    overview:
      'Ben Sanderson, an alcoholic Hollywood screenwriter who lost everything because of his drinking, arrives in Las Vegas to drink himself to death. There, he meets and forms an uneasy friendship and non-interference pact with prostitute Sera.',
    release_date: '1995-10-27',
    runtime: 111,
    poster_path: '/wIfP6uLXD9Ptu68SyRx8WuSNNSK.jpg',
    tmdb_validation_status: 'not_checked',
  }),
  withMetadata({
    movie_id: 10,
    title: 'GoldenEye (1995)',
    genres: ['Action', 'Adventure', 'Thriller'],
    tmdb_id: 710,
    imdb_id: 113189,
    overview:
      'When a powerful secret defense system is stolen, James Bond is assigned to stop a Russian crime syndicate from using it.',
    release_date: '1995-11-16',
    runtime: 130,
    poster_path: '/z0ljRnNxIO7CRBhLEO0DvLgAFPR.jpg',
    tmdb_validation_status: 'valid',
  }),
  withMetadata({
    movie_id: 36,
    title: 'Dead Man Walking (1995)',
    genres: ['Crime', 'Drama'],
    tmdb_id: 687,
    imdb_id: 112818,
    overview:
      'A death row inmate turns for spiritual guidance to a local nun in the days leading up to his scheduled execution for the murders of a young couple.',
    release_date: '1995-12-29',
    runtime: 122,
    poster_path: '/eShxyjhWoFl3BwsuEmVsr4nLaMZ.jpg',
    tmdb_validation_status: 'not_checked',
  }),
  withMetadata({
    movie_id: 17,
    title: 'Sense and Sensibility (1995)',
    genres: ['Drama', 'Romance'],
    tmdb_id: 4584,
    imdb_id: 114388,
    overview:
      'The Dashwood sisters, sensible Elinor and passionate Marianne, learn that their prospects of marriage seem doomed by their family\'s sudden loss of fortune.',
    release_date: '1995-12-13',
    runtime: 136,
    poster_path: '/cBK2yL3HqhFvIVd7lLtazWlRZPR.jpg',
    tmdb_validation_status: 'valid',
  }),
  {
    // No poster: this movie has no TMDB ID in the catalogue (real current state).
    movie_id: 7842,
    title: 'Dune (2000)',
    genres: ['Drama', 'Fantasy', 'Sci-Fi'],
    tmdb_id: null,
    imdb_id: 142032,
    overview: null,
    release_date: null,
    runtime: null,
    poster_path: null,
    poster_url: null,
    metadata_status: 'no_tmdb_id',
    metadata_updated_at: null,
    tmdb_validation_status: 'not_checked',
  },
  withMetadata({
    movie_id: 1,
    title: 'Toy Story (1995)',
    genres: ['Adventure', 'Animation', 'Children', 'Comedy', 'Fantasy'],
    tmdb_id: 862,
    imdb_id: 114709,
    overview:
      "Led by Woody, Andy's toys live happily in his room until Andy's birthday brings Buzz Lightyear onto the scene. Afraid of losing his place in Andy's heart, Woody plots against Buzz.",
    release_date: '1995-11-22',
    runtime: 81,
    poster_path: '/uXDfjJbdP4ijW5hWSBrPrlKpxab.jpg',
    tmdb_validation_status: 'valid',
  }),
]

/** Look up a demo movie by ID (used by the movie details preview page). */
export function findDemoMovie(movieId: number): MovieDetails | undefined {
  if (movieId === demoFeaturedMovie.movie_id) return demoFeaturedMovie
  return demoCatalogueMovies.find((movie) => movie.movie_id === movieId)
}

/**
 * MovieLens genres in the catalogue (from the movies table, 22 November 2026).
 * "IMAX" (a format, not a genre) and "(no genres listed)" are left out.
 * There is no genres endpoint yet; this list is shown as disabled chips.
 */
export const CATALOGUE_GENRES = [
  'Action', 'Adventure', 'Animation', 'Children', 'Comedy', 'Crime',
  'Documentary', 'Drama', 'Fantasy', 'Film-Noir', 'Horror', 'Musical',
  'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western',
]
