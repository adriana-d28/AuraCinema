// The poster fallback is a requirement (FR-3): a missing or broken poster must
// show the placeholder, never a broken image.
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MoviePoster } from './MoviePoster'

describe('MoviePoster', () => {
  it('shows the placeholder when the API sends no poster address', () => {
    render(<MoviePoster posterUrl={null} title="Dune" alt="Poster of Dune" />)

    expect(screen.getByRole('img', { name: 'No poster available for Dune' })).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Poster of Dune' })).not.toBeInTheDocument()
  })

  it('replaces the image with the placeholder when the image fails to load', () => {
    render(<MoviePoster posterUrl="https://image.tmdb.org/t/p/w500/x.jpg" title="Heat" alt="Poster of Heat" />)

    // jsdom never downloads images, so the failure is simulated.
    fireEvent.error(screen.getByRole('img', { name: 'Poster of Heat' }))

    expect(screen.getByRole('img', { name: 'No poster available for Heat' })).toBeInTheDocument()
  })
})
