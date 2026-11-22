// Shows a movie poster, or a designed placeholder when there is no image.
//
// The poster box always has the 2:3 shape of a film poster (CSS aspect-ratio),
// whether the image exists, is still loading, or failed. Because the box size
// never changes, grids and hero sections keep their layout in every case.
//
// The placeholder is used when:
//   1. the API sends poster_url = null (no poster stored, see metadata_status);
//   2. the image address exists but the image fails to load (onError).
//
// The image comes from the poster_url provided by the backend. This component
// never builds TMDB addresses itself and never calls TMDB.

import { useState } from 'react'
import styles from './MoviePoster.module.css'

interface MoviePosterProps {
  posterUrl: string | null
  /** Display title, written on the placeholder (e.g. "The Matrix"). */
  title: string
  /**
   * Text alternative for screen readers. Use "" when the title is already
   * written next to the poster (as in a movie card), so it is not read twice.
   */
  alt: string
  /** "eager" for the main hero poster (visible immediately); "lazy" elsewhere. */
  loading?: 'eager' | 'lazy'
  className?: string
}

export function MoviePoster({ posterUrl, title, alt, loading = 'lazy', className }: MoviePosterProps) {
  // Remember which address failed. If the address changes later (another
  // movie), the new image is tried again automatically.
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  // Used to fade the image in once it has arrived, instead of it popping in.
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null)

  const showImage = posterUrl !== null && posterUrl !== failedUrl
  const classes = [styles.poster, className].filter(Boolean).join(' ')

  return (
    <div className={classes}>
      {showImage ? (
        <img
          src={posterUrl}
          alt={alt}
          loading={loading}
          decoding="async"
          className={`${styles.image} ${loadedUrl === posterUrl ? styles.loaded : ''}`}
          onLoad={() => setLoadedUrl(posterUrl)}
          onError={() => setFailedUrl(posterUrl)}
        />
      ) : (
        <PosterPlaceholder title={title} alt={alt} />
      )}
    </div>
  )
}

// The fallback "poster": the film title set in the editorial serif inside a
// thin gold frame, on a dark burgundy gradient. It fits the visual identity,
// so a missing image looks intentional rather than broken.
function PosterPlaceholder({ title, alt }: { title: string; alt: string }) {
  // When the poster is decorative (alt=""), the placeholder is hidden from
  // screen readers too; otherwise it is announced as an image.
  const a11yProps =
    alt === '' ? { 'aria-hidden': true } : { role: 'img', 'aria-label': `No poster available for ${title}` }

  return (
    <div className={styles.placeholder} {...a11yProps}>
      <span className={styles.placeholderTitle}>{title}</span>
      <span className={styles.placeholderLabel}>No poster</span>
    </div>
  )
}
