// Pure display logic: cheap to test.
import { describe, expect, it } from 'vitest'
import { formatRuntime } from './movieFormat'

describe('formatRuntime', () => {
  it('writes minutes as hours and minutes', () => {
    expect(formatRuntime(170)).toBe('2h 50m')
    expect(formatRuntime(45)).toBe('45m')
  })
})
