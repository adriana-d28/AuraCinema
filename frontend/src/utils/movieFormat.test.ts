// Pure display logic: easy to get wrong with real MovieLens titles, cheap to test.
import { describe, expect, it } from 'vitest'
import { formatMovieTitle, formatRuntime } from './movieFormat'

describe('formatMovieTitle', () => {
  it('turns MovieLens titles into display titles and years', () => {
    expect(formatMovieTitle('Matrix, The (1999)')).toEqual({ title: 'The Matrix', year: 1999 })
    expect(formatMovieTitle('Twelve Monkeys (a.k.a. 12 Monkeys) (1995)')).toEqual({ title: 'Twelve Monkeys', year: 1995 })
    expect(formatMovieTitle('City of Lost Children, The (Cité des enfants perdus, La) (1995)')).toEqual({
      title: 'The City of Lost Children',
      year: 1995,
    })
    expect(formatMovieTitle('Untitled')).toEqual({ title: 'Untitled', year: null })
  })
})

describe('formatRuntime', () => {
  it('writes minutes as hours and minutes', () => {
    expect(formatRuntime(170)).toBe('2h 50m')
    expect(formatRuntime(45)).toBe('45m')
  })
})
